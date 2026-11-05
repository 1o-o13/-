"""코딩 테스트 API 시험 (judge 컨테이너 필요, worker는 eager). 실행: pytest -q api/test_coding.py
문제 모음 대신 작은 A+B 문제를 슬롯·등급마다 넣어 빠르게 돈다. 3번 LLM 출제는 _ask를 바꿔 끼워 검증 경로만 본다.
"""
import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from api.coding import q3, rules
from api.test_interview_flow import OK_CHECK, as_candidate, has_score, sql
from seed.coding_bank import slot3

N = 47                                          # 다른 시험이 안 쓰는 지원자. 수준 상 → 시험 결과 골드3(상)과 시드 규칙 D-05가 맞음
RIGHT = "a, b = map(int, input().split())\nprint(a + b)\n"
HALF = "a, b = map(int, input().split())\nprint(a + b if a < 1000 else 0)\n"      # 큰 입력(그룹 3~5)에서 틀림
JAVA = ("import java.util.*;\npublic class Main { public static void main(String[] x) { Scanner s = new Scanner(System.in);"
        " long a = s.nextLong(), b = s.nextLong(); System.out.println(a + b); } }\n")


def _toy(c, slot: int, tier: str) -> None:
    pid = c.execute("""INSERT INTO coding_problem(slot, tier, type, mode, origin, statement, solution_python, solution_java, generator,
                           validator, seed, time_limits, prompt_version, validated_at)
                       VALUES (%s, %s, 'BFS', 'stdio', 'collected', '# 두 수 더하기', %s, %s, '-', '-', 1, %s, 'test', now())
                       RETURNING id""", (slot, tier, RIGHT, JAVA, Jsonb({"python": 2000, "java": 3000}))).fetchone()["id"]
    rows = [(pid, 0, 1, "1 2\n", "3\n", True)]
    rows += [(pid, n, g, f"{a} {a + 1}\n", f"{2 * a + 1}\n", False)
             for n, (g, a) in enumerate([(g, 10 ** g + k) for g in range(1, 6) for k in range(2)], 1)]
    c.cursor().executemany("INSERT INTO coding_case(problem_id, case_no, size, input, expected, is_sample) VALUES (%s,%s,%s,%s,%s,%s)", rows)


@pytest.fixture(scope="module")
def coding_app(db_url):
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as c:
        if not c.execute("SELECT 1 FROM coding_problem WHERE prompt_version = 'test'").fetchone():
            for slot in (1, 2):
                _toy(c, slot, rules.Q12_TIER)
            for tier in rules.TIERS:
                _toy(c, 3, tier)
        c.execute("""DELETE FROM coding_session WHERE application_id IN (SELECT a.id FROM application a JOIN candidate d ON d.id = a.candidate_id
                     WHERE d.email = %s)""", (f"cand{N:02d}@test.local",))
        c.execute("""UPDATE job_posting SET job_category = 'dev' WHERE id IN (SELECT a.posting_id FROM application a
                     JOIN candidate d ON d.id = a.candidate_id WHERE d.email = %s)""", (f"cand{N:02d}@test.local",))
    return db_url


def test_rules():
    assert [rules.q3_tier(p, p) for p in (90, 70, 50, 30, 10)] == ["골드2", "골드3", "골드4", "골드5", "실버1"]
    assert rules.converted("골드3", 50) == 65 and rules.converted("실버1", 0) == 0 and rules.converted("골드2", 100) == 100


def test_coding_flow(client, coding_app, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)           # 3번은 문제 모음 대체 경로로 (실제 출제는 따로 확인)
    app_id = as_candidate(client, N)
    g = client.get(f"/api/interview/applications/{app_id}/guide").json()
    assert g["can_start"] and g["coding_required"] and g["coding_status"] is None      # 코딩 전이어도 점검까지는 간다
    assert client.post(f"/api/coding/applications/{app_id}/start").status_code == 409     # 점검·본인 확인 전에는 못 봄
    assert client.post(f"/api/interview/applications/{app_id}/precheck", json=OK_CHECK).status_code == 200
    client.post(f"/api/interview/applications/{app_id}/identity", files={"frame": ("f.jpg", b"jpeg", "image/jpeg")})
    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 409   # 코딩 전에는 면접 준비 안 됨

    csid = client.post(f"/api/coding/applications/{app_id}/start").json()["session_id"]
    assert client.post(f"/api/coding/applications/{app_id}/start").json()["session_id"] == csid   # 다시 눌러도 같은 응시
    st = client.get(f"/api/coding/sessions/{csid}/state").json()
    assert st["phase"] == "q12" and [p["slot"] for p in st["problems"]] == [1, 2] and 0 < st["remaining_sec"] <= 90 * 60
    assert st["problems"][0]["examples"] == [{"input": "1 2\n", "output": "3\n"}]
    assert "expected" not in str(st) and not has_score(st)

    r = client.post(f"/api/coding/sessions/{csid}/run", json={"slot": 1, "language": "java", "code": JAVA}).json()
    assert r["results"][0]["verdict"] == "AC"
    r = client.post(f"/api/coding/sessions/{csid}/submit", json={"slot": 1, "language": "python", "code": "print(oops"}).json()
    assert r["passed"] == 0 and r["total"] == 10
    r = client.post(f"/api/coding/sessions/{csid}/submit", json={"slot": 1, "language": "python", "code": RIGHT}).json()
    assert r["passed"] == 10 and set(r) == {"compile_error", "passed", "total", "groups"}        # 통과 수만 (CT-34)
    r = client.post(f"/api/coding/sessions/{csid}/submit", json={"slot": 2, "language": "python", "code": HALF}).json()
    assert r["passed"] == 4 and r["groups"]["5"] == "0/2"

    assert client.post(f"/api/coding/sessions/{csid}/finish-12").status_code == 200           # eager: 3번이 바로 준비됨
    st = client.get(f"/api/coding/sessions/{csid}/state").json()
    assert st["phase"] == "q3" and st["problems"][0]["closed"] and not st["problems"][2]["closed"]
    assert client.post(f"/api/coding/sessions/{csid}/submit", json={"slot": 1, "language": "python", "code": RIGHT}).status_code == 409
    a3 = sql(coding_app, "SELECT a.assigned_reason, p.tier FROM coding_attempt a JOIN coding_problem p ON p.id = a.problem_id "
                         "WHERE a.session_id = %s AND a.slot = 3", csid)[0]
    assert a3["tier"] == "골드3" and a3["assigned_reason"]["fallback"]["q3"] == "문제 모음 대체"   # 평균 70 → 골드3, 키 없음 → 대체
    client.post(f"/api/coding/sessions/{csid}/submit", json={"slot": 3, "language": "python", "code": HALF})
    assert client.post(f"/api/coding/sessions/{csid}/finish").status_code == 200

    res = sql(coding_app, "SELECT * FROM coding_result WHERE session_id = %s", csid)[0]
    assert (float(res["p1"]), float(res["p2"]), res["q3_tier"], float(res["q3_partial"])) == (100, 40, "골드3", 40)
    assert float(res["q3_converted"]) == 45 + 16 and res["fallback_flags"]["q3"] == "문제 모음 대체"
    assert res["weakness_summary"]["algorithms"] == ["BFS"] and res["weakness_summary"]["failed_groups"] == [3, 4, 5]
    assert sql(coding_app, "SELECT count(*) AS n FROM coding_review r JOIN coding_attempt a ON a.id = r.attempt_id "
                           "WHERE a.session_id = %s", csid)[0]["n"] == 3
    assert client.get(f"/api/coding/sessions/{csid}/state").json()["phase"] == "done"

    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 200    # 코딩 뒤에는 면접 준비
    s = sql(coding_app, "SELECT coding_session_id, coding_weakness, ct_band FROM interview_session WHERE application_id = %s", app_id)[0]
    assert s["coding_session_id"] == csid and s["ct_band"] == "상" and s["coding_weakness"]["algorithms"] == ["BFS"]


def test_other_candidate_forbidden(client, coding_app):
    csid = sql(coding_app, "SELECT max(id) AS id FROM coding_session")[0]["id"]
    as_candidate(client, 44)
    assert client.get(f"/api/coding/sessions/{csid}/state").status_code == 403


def test_q3_generated_passes_checks(db_url, monkeypatch):
    """LLM 출제 경로: 출제 응답(문제 모음의 실버1 문제) → 기계 검증 → AI 검증 통과 → generated로 저장"""
    calls = []
    keys = ("title", "type", "statement", "examples", "solution_python", "solution_java", "brute_force", "generator", "validator",
            "wrong_codes")

    def fake(model, system, human):
        calls.append(system == q3.GEN_SYSTEM)
        return {k: slot3.SORT[k] for k in keys} if system == q3.GEN_SYSTEM else {"ok": True, "issues": [], "tier_fit": "맞음"}
    monkeypatch.setattr(q3, "_ask", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as c:
        pid, reason = q3.prepare(c, "실버1", {"algorithms": ["정렬"], "weakness_tags": []})
        p = c.execute("SELECT origin, prompt_version FROM coding_problem WHERE id = %s", (pid,)).fetchone()
    assert calls == [True, False] and reason["origin"] == "generated" and p == {"origin": "generated", "prompt_version": q3.PROMPT_VERSION}


def test_q3_falls_back_after_failed_checks(db_url, monkeypatch):
    """AI 검증이 두 번 다 거절 → 같은 등급 문제 모음으로 대체, 이유 기록. LLM 호출 4번 (상한 7 안)"""
    calls = []

    def fake(model, system, human):
        calls.append(1)
        if system == q3.GEN_SYSTEM:
            return {k: slot3.SORT[k] for k in ("title", "type", "statement", "examples", "solution_python", "solution_java",
                                               "brute_force", "generator", "validator", "wrong_codes")}
        return {"ok": False, "issues": ["지문 모호"], "tier_fit": "쉬움"}
    monkeypatch.setattr(q3, "_ask", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as c:
        _, reason = q3.prepare(c, "실버1", {"algorithms": ["정렬"]})
    assert len(calls) == 4 and reason["origin"] == "collected"
    assert [x["step"] for x in reason["fallback"]["log"]] == ["AI 검증", "AI 검증"]


def test_q3_stuck_falls_back_and_finalize_once(client, coding_app):
    """3번 준비가 10분 넘게 안 끝나면(worker 중단 등) 상태 조회 때 문제 모음으로 내고, 마감은 겹쳐도 한 번만"""
    from api.coding import routes
    app_id = as_candidate(client, 46)
    with psycopg.connect(coding_app, autocommit=True, row_factory=dict_row) as c:
        # 시드 코딩 결과(1차 응시)는 다른 시험이 쓰므로 두고, 2차 응시를 만들어 시험한 뒤 지운다
        csid = c.execute("INSERT INTO coding_session(application_id, attempt_no) VALUES (%s, 2) RETURNING id", (app_id,)).fetchone()["id"]
        for slot in (1, 2):
            c.execute("""INSERT INTO coding_attempt(session_id, slot, problem_id, language, ended_at)
                         SELECT %s, %s, id, 'python', now() - interval '11 minutes' FROM coding_problem
                         WHERE slot = %s AND prompt_version = 'test' LIMIT 1""", (csid, slot, slot))
    st = client.get(f"/api/coding/sessions/{csid}/state").json()
    assert st["phase"] == "q3"                                           # 기다리지 않고 3번이 열림
    a3 = sql(coding_app, "SELECT assigned_reason FROM coding_attempt WHERE session_id = %s AND slot = 3", csid)[0]
    assert a3["assigned_reason"]["fallback"]["q3"] == "출제 지연으로 문제 모음 대체" and a3["assigned_reason"]["tier"] == "실버1"
    with psycopg.connect(coding_app, autocommit=True, row_factory=dict_row) as c:
        routes.finalize(c, csid)
        routes.finalize(c, csid)                                         # 두 번째는 아무것도 안 함 (전에는 500)
    assert sql(coding_app, "SELECT count(*) AS n FROM coding_review r JOIN coding_attempt a ON a.id = r.attempt_id "
                           "WHERE a.session_id = %s", csid)[0]["n"] == 3
    with psycopg.connect(coding_app, autocommit=True) as c:
        c.execute("DELETE FROM coding_session WHERE id = %s", (csid,))
