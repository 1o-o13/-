"""코딩 테스트 API (CAN-010, prefix /api/coding). 사전 점검·본인 확인(화상면접과 공용) 뒤, AI 화상면접 안내 전에 본다.

1·2번: 기본 등급(골드3) 문제 모음에서 무작위 배정 → 예제 실행·제출(무제한, 서버 채점)
1·2번 완료 → 부분 점수 평균으로 3번 등급 → 3번 준비 (worker: LLM 출제·검증, 안 되면 같은 등급 모음 문제)
3번 완료(또는 시간 종료) → 환산 점수·코드 리뷰·약점 요약 → coding_result (화상면접 3번 질문 입력)
지원자 응답에는 통과 수만 넣는다. 등급·점수·숨긴 케이스·정답·출제 근거는 넣지 않는다 (CT-34)
"""
import random
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from api.auth import current_candidate, own_application
from api import stage

from api.coding import judge, rules
from api.db import get_db
from api.graph import main as main_graph
from api.interview import store

router = APIRouter(prefix="/api/coding")
Q3_WAIT_MAX_SEC = 600          # 임시: 3번 준비가 이보다 오래 걸리면(worker 중단 등) 같은 등급 문제 모음으로 바로 낸다

TEMPLATES = {
    "python": "import sys\n\n\ndef main():\n    data = sys.stdin.read().split()\n    # 여기에 풀이를 작성하세요\n\n\nmain()\n",
    "java": "import java.io.*;\nimport java.util.*;\n\npublic class Main {\n    public static void main(String[] args) throws IOException {\n"
            "        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));\n        // 여기에 풀이를 작성하세요\n    }\n}\n",
}
RUNTIME = {"python": "Python 3.12 (표준 입출력, 재귀 한도 기본 1000 → sys.setrecursionlimit으로 늘릴 수 있음)",
           "java": "Java 21 (클래스 이름 Main, 표준 입출력, 스택 64MB·힙 256MB)"}


def own_session(csid: int, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")) -> int:
    row = db.execute("""SELECT a.candidate_id FROM coding_session s JOIN application a ON a.id = s.application_id WHERE s.id = %s""",
                     (csid,)).fetchone()
    if row is None:
        raise HTTPException(404, "응시가 없습니다")
    if row["candidate_id"] != candidate_id:
        raise HTTPException(403, "본인 응시만 볼 수 있습니다")
    return csid


@router.get("/applications/{app_id}/session")
def my_session(app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    """이 지원서의 최근 코딩 응시 (없으면 null). 안내·점검 화면이 다음 화면을 고를 때 쓴다"""
    return db.execute("SELECT id, status FROM coding_session WHERE application_id = %s ORDER BY attempt_no DESC LIMIT 1",
                      (app_id,)).fetchone()


@router.post("/applications/{app_id}/start")
def start(app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    """코딩 테스트 시작: 1·2번 배정. 이미 시작했으면 그 응시를 그대로 (새로고침·재접속, CT-30)"""
    a = db.execute("""SELECT a.status, p.job_category, now() BETWEEN p.stage2_start AND p.stage2_end AS in_window
                      FROM application a JOIN job_posting p ON p.id = a.posting_id WHERE a.id = %s""", (app_id,)).fetchone()
    if a["status"] != "stage2" or a["job_category"] != "dev" or not a["in_window"]:
        raise HTTPException(409, "코딩 테스트를 볼 수 있는 지원서가 아닙니다")
    cur = db.execute("SELECT id, status FROM coding_session WHERE application_id = %s ORDER BY attempt_no DESC LIMIT 1", (app_id,)).fetchone()
    if cur and cur["status"] == "in_progress":
        return {"session_id": cur["id"]}
    if cur:
        raise HTTPException(409, "이미 코딩 테스트를 마쳤습니다")
    s = db.execute("""SELECT status, identity_status, precheck FROM interview_session WHERE application_id = %s
                      ORDER BY attempt_no DESC LIMIT 1""", (app_id,)).fetchone()
    if not s or s["status"] != "prechecked":
        raise HTTPException(409, "사전 점검·본인 확인을 먼저 해 주세요")
    why = store.identity_ok(s)
    if why:
        raise HTTPException(409, why)
    picks = []
    for slot in (1, 2):
        pool = [r["id"] for r in db.execute("""SELECT id FROM coding_problem WHERE slot = %s AND tier = %s AND origin = 'collected'
                                                 AND validated_at IS NOT NULL""", (slot, rules.Q12_TIER)).fetchall()]
        if not pool:
            raise HTTPException(503, "출제할 문제가 없습니다 (scripts/load_coding.py)")
        picks.append(random.SystemRandom().choice(pool))              # 등급 안에서 무작위 (지원자마다 다를 수 있음)
    try:
        with db.transaction():
            csid = db.execute("INSERT INTO coding_session(application_id) VALUES (%s) RETURNING id", (app_id,)).fetchone()["id"]
            for slot, pid in zip((1, 2), picks):
                db.execute("""INSERT INTO coding_attempt(session_id, slot, problem_id, language, assigned_reason)
                              VALUES (%s, %s, %s, 'python', %s)""", (csid, slot, pid, Jsonb({"tier": rules.Q12_TIER, "rule": "기본 등급 무작위"})))
    except psycopg.errors.UniqueViolation:          # 같은 요청이 겹쳐 먼저 끝난 쪽이 만들었음 (두 번 누름·새로고침)
        csid = db.execute("SELECT id FROM coding_session WHERE application_id = %s ORDER BY attempt_no DESC LIMIT 1", (app_id,)).fetchone()["id"]
    main_graph.advance(app_id, "wait_access")       # 메인 그래프: 지원자 접속 → 코딩 1·2번
    stage.move(db, app_id, "coding", "candidate")    # 상세 단계: 코딩 테스트
    return {"session_id": csid}


def _remaining(db, csid: int) -> float:
    """남은 초. 3번을 준비하는 동안(1·2번 끝 → 3번 배정)은 시간이 멈춘다 (임시: 출제 대기 시간을 지원자 시간에서 빼지 않음)"""
    return db.execute("""SELECT extract(epoch FROM s.started_at + make_interval(mins => cs.time_limit_min)
                                + coalesce(coalesce(a3.started_at, now()) - a1.ended_at, interval '0') - now())::float AS left
                         FROM coding_session s JOIN application a ON a.id = s.application_id
                         JOIN coding_setting cs ON cs.posting_id = a.posting_id
                         JOIN coding_attempt a1 ON a1.session_id = s.id AND a1.slot = 1
                         LEFT JOIN coding_attempt a3 ON a3.session_id = s.id AND a3.slot = 3 WHERE s.id = %s""", (csid,)).fetchone()["left"]


def _best(db, attempt_id: int) -> dict | None:
    return db.execute("""SELECT partial_score, case_results, group_scores FROM coding_submission WHERE attempt_id = %s
                         ORDER BY partial_score DESC, submitted_at DESC LIMIT 1""", (attempt_id,)).fetchone()


def _counts(case_results: list[dict]) -> dict:
    """지원자에게 보여 줄 통과 수: 전체·그룹별 (점수·등급 없음)"""
    g = {str(n): [0, 0] for n in range(1, judge.GROUPS + 1)}
    for c in case_results:
        g[str(c["size"])][1] += 1
        g[str(c["size"])][0] += c["verdict"] == "AC"
    return {"passed": sum(v[0] for v in g.values()), "total": sum(v[1] for v in g.values()),
            "groups": {k: f"{a}/{b}" for k, (a, b) in g.items()}}


def finalize(db, csid: int) -> None:
    """종료: 1·2·3번 가장 좋은 제출로 점수·등급·환산 점수, 코드 리뷰, 약점 요약 → coding_result, 응시 완료.
    시간 종료(상태 조회)와 끝내기가 겹쳐도 한 번만 한다 (응시 행을 먼저 잠그고 상태를 다시 본다)"""
    att = db.execute("""SELECT a.id, a.slot, a.assigned_reason, p.type, p.tier FROM coding_attempt a JOIN coding_problem p ON p.id = a.problem_id
                        WHERE a.session_id = %s ORDER BY a.slot""", (csid,)).fetchall()
    by = {a["slot"]: a for a in att}
    best = {a["slot"]: _best(db, a["id"]) for a in att}
    part = {s: float(best[s]["partial_score"]) if best.get(s) else 0.0 for s in (1, 2, 3)}
    base = rules.q3_tier(part[1], part[2])
    tier = by[3]["tier"] if 3 in by else base
    graded = [{"type": by[s]["type"], "partial": part[s], "case_results": best[s]["case_results"]} for s in by if best.get(s)]
    with db.transaction():
        if db.execute("SELECT status FROM coding_session WHERE id = %s FOR UPDATE", (csid,)).fetchone()["status"] != "in_progress":
            return                                              # 다른 요청이 먼저 마감함
        for s, a in by.items():
            r = rules.review({"type": a["type"], "partial": part[s], "case_results": best[s]["case_results"] if best.get(s) else []})
            db.execute("""INSERT INTO coding_review(attempt_id, rubric, summary, quality_level, model, prompt_version)
                          VALUES (%s, %s, %s, %s, 'stub', 'rule-v0')""", (a["id"], Jsonb(r["rubric"]), Jsonb(r["summary"]), r["quality_level"]))
        db.execute("UPDATE coding_attempt SET ended_at = coalesce(ended_at, now()) WHERE session_id = %s", (csid,))
        db.execute("""INSERT INTO coding_result(session_id, p1, p2, q3_base_tier, q3_tier, q3_partial, q3_converted, score_table_version,
                          fallback_flags, weakness_summary) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                   (csid, part[1], part[2], base, tier, part[3], rules.converted(tier, part[3]), rules.SCORE_TABLE,
                    Jsonb((by[3]["assigned_reason"] or {}).get("fallback")) if 3 in by else Jsonb({"q3": "시간 종료로 출제 전 끝남"}),
                    Jsonb(rules.weakness(graded) if graded else {"algorithms": [], "failed_groups": [], "weakness_tags": ["제출 없음"]})))
        db.execute("UPDATE coding_session SET status = 'completed', ended_at = now() WHERE id = %s", (csid,))


@router.get("/sessions/{csid}/state")
def state(csid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """남은 시간·단계·문제(지문·예제)·내 제출 통과 수. 시간이 끝났으면 여기서 마감한다 (CT-31)"""
    s = db.execute("SELECT status FROM coding_session WHERE id = %s", (csid,)).fetchone()
    left = _remaining(db, csid)
    if s["status"] == "in_progress" and left <= 0:
        finalize(db, csid)
        s = {"status": "completed"}
    att = db.execute("""SELECT a.id, a.slot, a.language, a.ended_at, p.id AS pid, p.statement, p.time_limits FROM coding_attempt a
                        JOIN coding_problem p ON p.id = a.problem_id WHERE a.session_id = %s ORDER BY a.slot""", (csid,)).fetchall()
    q12_done = any(a["slot"] == 1 and a["ended_at"] for a in att)
    if s["status"] == "in_progress" and q12_done and not any(a["slot"] == 3 for a in att):
        _q3_fallback_if_stuck(db, csid)
        att = db.execute("""SELECT a.id, a.slot, a.language, a.ended_at, p.id AS pid, p.statement, p.time_limits FROM coding_attempt a
                            JOIN coding_problem p ON p.id = a.problem_id WHERE a.session_id = %s ORDER BY a.slot""", (csid,)).fetchall()
    phase = "done" if s["status"] != "in_progress" else "q3" if any(a["slot"] == 3 for a in att) else "q3_preparing" if q12_done else "q12"
    problems = []
    for a in att:
        ex = db.execute("SELECT input, expected FROM coding_case WHERE problem_id = %s AND is_sample ORDER BY case_no", (a["pid"],)).fetchall()
        last = db.execute("SELECT case_results FROM coding_submission WHERE attempt_id = %s ORDER BY submitted_at DESC LIMIT 1",
                          (a["id"],)).fetchone()
        n = db.execute("SELECT count(*) AS n FROM coding_submission WHERE attempt_id = %s", (a["id"],)).fetchone()["n"]
        problems.append({"slot": a["slot"], "statement": a["statement"], "examples": [{"input": e["input"], "output": e["expected"]} for e in ex],
                         "language": a["language"], "time_limits": a["time_limits"], "closed": bool(a["ended_at"]) or s["status"] != "in_progress",
                         "submissions": n, "last": _counts(last["case_results"]) if last else None})
    return {"status": s["status"], "phase": phase, "remaining_sec": max(0, round(left)), "problems": problems,
            "templates": TEMPLATES, "runtime": RUNTIME}


def _q3_fallback_if_stuck(db, csid: int) -> None:
    """3번 준비가 Q3_WAIT_MAX_SEC를 넘으면 출제 작업을 기다리지 않고 같은 등급 문제 모음에서 낸다 (준비 중엔 시간이 멈춰 끝없이 기다리게 되므로)"""
    a1 = db.execute("""SELECT extract(epoch FROM now() - ended_at) AS waited FROM coding_attempt WHERE session_id = %s AND slot = 1""",
                    (csid,)).fetchone()
    if a1["waited"] < Q3_WAIT_MAX_SEC:
        return
    att = db.execute("""SELECT a.slot, (SELECT max(x.partial_score) FROM coding_submission x WHERE x.attempt_id = a.id) AS best
                        FROM coding_attempt a WHERE a.session_id = %s AND a.slot IN (1, 2) ORDER BY a.slot""", (csid,)).fetchall()
    tier = rules.q3_tier(*[float(a["best"] or 0) for a in att])
    pool = [r["id"] for r in db.execute("""SELECT id FROM coding_problem WHERE slot = 3 AND tier = %s AND origin = 'collected'
                                           AND validated_at IS NOT NULL""", (tier,)).fetchall()]
    db.execute("""INSERT INTO coding_attempt(session_id, slot, problem_id, language, assigned_reason) VALUES (%s, 3, %s, 'python', %s)
                  ON CONFLICT (session_id, slot) DO NOTHING""",
               (csid, random.SystemRandom().choice(pool), Jsonb({"tier": tier, "rule": "1·2번 평균 구간", "origin": "collected",
                                                                 "fallback": {"q3": "출제 지연으로 문제 모음 대체"}})))


class CodeIn(BaseModel):
    slot: int = Field(ge=1, le=3)
    language: Literal["python", "java"]
    code: str = Field(min_length=1, max_length=64_000)
    paste_attempts: int = Field(0, ge=0, le=10_000)      # 편집기에서 막은 붙여넣기 시도 수 (F-SYS-18)


def _open_attempt(db, csid: int, slot: int) -> dict:
    a = db.execute("""SELECT a.id, a.ended_at, p.id AS pid, p.time_limits, s.status FROM coding_attempt a JOIN coding_problem p ON p.id = a.problem_id
                      JOIN coding_session s ON s.id = a.session_id WHERE a.session_id = %s AND a.slot = %s""", (csid, slot)).fetchone()
    if a is None or a["ended_at"] or a["status"] != "in_progress" or _remaining(db, csid) <= 0:
        raise HTTPException(409, "지금 풀 수 있는 문항이 아닙니다")
    return a


@router.post("/sessions/{csid}/run")
def run_examples(body: CodeIn, csid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """예제 실행: 공개 예제만 돌려 출력·판정을 보여 준다 (점수에 안 들어감)"""
    a = _open_attempt(db, csid, body.slot)
    ex = db.execute("SELECT input, expected FROM coding_case WHERE problem_id = %s AND is_sample ORDER BY case_no", (a["pid"],)).fetchall()
    r = judge.run(body.language, body.code, [e["input"] for e in ex], a["time_limits"][body.language])
    return {"compile_error": r["compile_error"],
            "results": [{"input": e["input"], "expected": e["expected"], "output": x["stdout"][:5000], "stderr": x["stderr"][-1000:],
                         "verdict": judge.verdict(x, e["expected"]), "time_ms": x["time_ms"]} for e, x in zip(ex, r["results"])]}


@router.post("/sessions/{csid}/submit")
def submit(body: CodeIn, csid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """제출 채점: 숨긴 케이스 전부를 서버 실행기에서 (CT-20). 지원자에게는 전체·그룹별 통과 수만 (CT-34). 제출 무제한 (CT-25)"""
    a = _open_attempt(db, csid, body.slot)
    cases = db.execute("""SELECT case_no, size, input, expected FROM coding_case WHERE problem_id = %s AND NOT is_sample AND in_grading_set
                          ORDER BY case_no""", (a["pid"],)).fetchall()
    r = judge.run(body.language, body.code, [c["input"] for c in cases], a["time_limits"][body.language])
    rows, groups, partial = judge.grade(cases, r["results"])
    with db.transaction():
        db.execute("UPDATE coding_attempt SET language = %s WHERE id = %s", (body.language, a["id"]))
        db.execute("""INSERT INTO coding_submission(attempt_id, language, code, case_results, group_scores, partial_score, paste_attempts)
                      VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                   (a["id"], body.language, body.code, Jsonb(rows), Jsonb(groups), partial, body.paste_attempts))
    return {"compile_error": r["compile_error"], **_counts(rows)}


@router.post("/sessions/{csid}/finish-12")
def finish_12(csid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """1·2번 끝내기 → 더는 고칠 수 없고, 3번을 준비한다 (worker)"""
    from worker.tasks import prepare_q3
    _open_attempt(db, csid, 1)
    db.execute("UPDATE coding_attempt SET ended_at = now() WHERE session_id = %s AND slot IN (1, 2) AND ended_at IS NULL", (csid,))
    prepare_q3.delay(csid)
    main_graph.advance(_app_of(db, csid), "wait_ct2")   # 메인 그래프: 2번 제출 종료 → S1 (3번 준비)
    return {"preparing": True}


@router.post("/sessions/{csid}/finish")
def finish(csid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """3번까지 끝내기 → 마감 (리뷰·약점 요약은 여기서 만든다)"""
    _open_attempt(db, csid, 3)
    finalize(db, csid)
    main_graph.advance(_app_of(db, csid), "wait_ct_end")   # 메인 그래프: 3번 종료 → finalize → 화상 면접 장치 점검 대기
    from worker.tasks import prepare_q3_question
    prepare_q3_question.delay(_app_of(db, csid))            # 코딩 약점이 생겼으니 면접 3번을 바로 만들고 검증
    return {"done": True}


def _app_of(db, csid: int) -> int:
    return db.execute("SELECT application_id FROM coding_session WHERE id = %s", (csid,)).fetchone()["application_id"]
