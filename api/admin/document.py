"""1차(서류) 결정과 결과 발표 (ADM-040, F-ADM-19). 활동다이어그램 1109 2쪽(S0).
- 1차 점수는 어디에도 없다. AI는 우대 항목별 라벨·원문 인용과 결론(추천·비추천·빈칸 = 'AI 추천(참고)')만 내고, 결정은 담당관이 한다
- AI 1차 검토: 접수 마감 뒤 일괄로 지원 건마다 메인 그래프 S0을 돌린다 (비교 검색 → LLM 의견 → 코드 검증 → hr_screen에서 멈춤)
- 결정 (11/10, 11/11): 담당관이 AI 추천을 보고 합격자만 체크박스로 고른 뒤 '결정 확인'을 한 번 누른다. 기록은 쌓기만 한다(최근 결정이 유효)
- 일괄 확정(발표): 고른 사람은 합격 → 2차 대상(stage2)·응시 안내 발송, 고르지 않은 사람은 모두 불합격(doc_failed). 따로 지정하지 않는다.
  메일·문자(가짜 발송) + 홈페이지 알림. 응시 안내 발송은 담당관이 이 버튼으로 직접 한다 (자동 발송 없음)
- 하드 필터(경력 구간 자동 탈락)는 없다 (11/12 제거): 모든 지원자를 담당관이 AI 근거를 보고 고른다
- 발표 뒤 합격 취소: 부정행위(지원서와 지원자가 다름 등)를 발견한 경우만. 사유 필수, 결정자·시각을 기록 (상세 단계 screen_rejected)
- AI 결론은 추천·비추천 두 가지 (보류 없음, 11/12). 추천은 공고 지원자의 30%까지(screen.final_conclusions).
  합격은 추천(또는 AI 정리 실패로 빈칸)에서만 고를 수 있다
- 기본 정렬: AI 추천 → 빈칸 → 비추천, 같은 결론 안에서는 '충족' 항목이 많은 순 (1차 점수는 없음)
- 평가 기준(document_criteria): 공고에 필요한 기술·경험. 모두 우대 (없어도 지원 가능)
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from api import notify, screen, stage
from api.admin.routes import READ, WRITE
from api.db import get_db
from api.graph import main as main_graph

router = APIRouter(prefix="/api/admin")
ORDER = {"추천": 0, None: 1, "비추천": 2}


def _announced(db, pid: int) -> dict | None:
    return db.execute("""SELECT n.status, n.published_at, u.name AS published_by FROM announcement n
                         LEFT JOIN admin_user u ON u.id = n.published_by
                         WHERE n.posting_id = %s AND n.stage = 'document' AND n.status IN ('published', 'corrected')""", (pid,)).fetchone()


def _view(cs: dict | None) -> dict:
    """기본 화면 값: 결론·근거(항목 이름 + 이력서 원문)·수상·자격 의견·업무 가능성·종합 의견. '상세'에만 항목 ID·라벨·검색 수치"""
    if not cs or "결론" not in cs:
        return {"screened": False}
    names = {r["id"]: r["text"] for r in cs.get("요건", [])}
    labels = {x["req_id"]: x for x in cs.get("labels", [])}
    basis = cs.get("결론 근거") or {}
    return {"screened": True, "conclusion": cs.get("결론"), "llm_conclusion": cs.get("결론"), "verify": cs.get("검증"),
            "basis": [{"req": names.get(i, i), "label": labels.get(i, {}).get("label"), "quote": labels.get(i, {}).get("quote")}
                      for i in basis.get("요건", [])],
            "awards_opinion": cs.get("awards_opinion"), "work_fit": cs.get("work_fit"), "overall": cs.get("overall"), "model": cs.get("model"),
            "detail": {"labels": [{**x, "req": names.get(x["req_id"], x["req_id"])} for x in cs.get("labels", [])],
                       "retrieval": {k: [{kk: d[kk] for kk in ("chunk_id", "rrf", "bm25", "vector")} for d in v]
                                     for k, v in (cs.get("비교") or {}).items()}}}


def _met(ai: dict) -> int:
    return sum(x.get("label") == "충족" for x in (ai.get("detail") or {}).get("labels", []))


@router.get("/postings/{pid}/document")
def document_board(pid: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """1차 서류 결정 화면: AI 추천 순. seq = 공고 안에서의 지원 번호 (1부터, 지원한 순서. id는 전체 지원서 번호라 공고마다 1부터가 아님, 11/12). 지원자별 AI 결론·근거·담당관 결정(최근)·결정 기록·상세 단계·알림 발송 기록 + 평가 기준"""
    p = db.execute("""SELECT id, title, headcount, apply_end, doc_announce_at, stage2_start, stage2_end FROM job_posting
                      WHERE id = %s""", (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "공고가 없습니다")
    rows = db.execute("""SELECT a.id, (SELECT count(*) FROM application x WHERE x.posting_id = a.posting_id AND x.id <= a.id) AS seq,
                                a.status, vs.stage, c.name, c.email, d.criteria_scores, d.handoff->>'deficit_value' AS deficit_value,
                                d.handoff->'deficit_evidence' AS deficit_evidence,
                                sr.result AS decision, sr.reason AS decision_reason, sr.decided_at, u.name AS decided_by,
                                (SELECT coalesce(jsonb_agg(jsonb_build_object('decision', l.detail->>'decision', 'reason', l.detail->>'reason',
                                                                              'by', lu.name, 'at', l.created_at) ORDER BY l.id), '[]')
                                 FROM audit_log l LEFT JOIN admin_user lu ON lu.id = l.actor_id
                                 WHERE l.action IN ('screen_decision', 'screen_revoke') AND l.target_id = a.id) AS history,
                                (SELECT coalesce(jsonb_agg(jsonb_build_object('channel', n.channel, 'status', n.status, 'sent_at', n.sent_at)
                                                           ORDER BY n.channel), '[]')
                                 FROM notification n JOIN announcement x ON x.id = n.announcement_id
                                 WHERE n.candidate_id = c.id AND x.posting_id = a.posting_id AND x.stage = 'document') AS notified
                         FROM application a JOIN candidate c ON c.id = a.candidate_id
                         JOIN v_application_stage vs ON vs.application_id = a.id
                         LEFT JOIN LATERAL (SELECT * FROM document_evaluation WHERE application_id = a.id ORDER BY version_no DESC LIMIT 1) d ON true
                         LEFT JOIN stage_result sr ON sr.application_id = a.id AND sr.stage = 'document'
                         LEFT JOIN admin_user u ON u.id = sr.decided_by
                         WHERE a.posting_id = %s AND a.status NOT IN ('withdrawn')
                         ORDER BY a.id""", (pid,)).fetchall()
    final = screen.final_conclusions(db, pid)          # 상위 30%만 추천 (11/12)
    out = []
    for r in rows:
        last = r["history"][-1]["decision"] if r["history"] else None
        ai = _view(r["criteria_scores"])
        if ai["screened"]:
            ai["conclusion"] = final.get(r["id"])
        out.append({k: v for k, v in r.items() if k != "criteria_scores"} | {"ai": ai, "latest": last,
                   "decision": "reject" if r["decision"] == "fail" else r["decision"], "stage_label": stage.LABEL.get(r["stage"], r["stage"])})
    out.sort(key=lambda r: (ORDER.get(r["ai"].get("conclusion"), 2), -_met(r["ai"]), r["id"]))
    return {"posting": p, "announcement": _announced(db, pid), "rows": out, "criteria": screen.criteria(db, pid)}


@router.post("/postings/{pid}/document/screen")
def screen_all(pid: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """AI 1차 검토 (접수 마감 뒤 일괄): 서류 심사 중인 지원 건마다 S0을 돌린다 (worker). 이미 돌린 건은 그대로"""
    from worker.tasks import screen_application
    if _announced(db, pid):
        raise HTTPException(409, "이미 발표했습니다")
    screen.criteria(db, pid)                         # 평가 기준이 비어 있으면 먼저 채운다 (작업들이 동시에 채우지 않게)
    ids = [r["id"] for r in db.execute("SELECT id FROM application WHERE posting_id = %s AND status = 'submitted' ORDER BY id",
                                       (pid,)).fetchall()]
    for i in ids:
        screen_application.delay(i)
    return {"queued": len(ids)}


class DocIn(BaseModel):
    decision: Literal["pass", "reject", "hold"]       # 화면: 합격 선택 = pass, 선택 해제 = hold (일괄 확정 때 고르지 않은 사람은 불합격)
    reason: str | None = Field(None, max_length=300)


def _check(db, app_id: int, decision: str) -> str:
    """담당관 1차 결정 (hr_screen 재개). 발표 전·서류 심사 중인 지원서만. AI 검토가 끝난 지원 건만 (S0이 hr_screen에서 기다림)"""
    a = db.execute("SELECT posting_id, status FROM application WHERE id = %s", (app_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "지원서가 없습니다")
    if _announced(db, a["posting_id"]) or a["status"] != "submitted":
        raise HTTPException(409, "이미 1차 결과를 발표해서 바꿀 수 없습니다")
    if decision == "pass" and screen.final_conclusions(db, a["posting_id"]).get(app_id) == "비추천":
        raise HTTPException(409, "AI 비추천 지원자는 합격으로 고를 수 없습니다 (합격은 추천 안에서)")
    phase = main_graph.waiting(app_id)               # hr_screen(결정 대기) 또는 wait_invite(합격 뒤 발송 전 → 다시 결정)
    if phase not in ("hr_screen", "wait_invite"):
        raise HTTPException(409, "AI 1차 검토를 먼저 실행해 주세요")
    return phase


def _decide(db, app_id: int, decision: str, admin: dict, reason: str | None = None) -> None:
    main_graph.advance(app_id, _check(db, app_id, decision), decision=decision, admin_id=admin["id"], reason=reason)


@router.post("/applications/{app_id}/document")
def decide_document(app_id: int, body: DocIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    _decide(db, app_id, body.decision, admin, body.reason)
    return {"decision": body.decision}


class AnnounceIn(BaseModel):
    pass_ids: list[int] | None = None                # 화면 체크박스로 고른 합격자 (11/11). 없으면 지금까지 고른 결정 그대로


def _apply_picks(db, pid: int, ids: set[int], admin: dict) -> None:
    """체크박스 결정을 한 번에 기록: 체크한 사람 = pass, 전에 골랐다가 체크를 뺀 사람 = hold (기록은 쌓기만)"""
    cur = {r["id"]: r["result"] for r in db.execute("""SELECT a.id, sr.result FROM application a
                 LEFT JOIN stage_result sr ON sr.application_id = a.id AND sr.stage = 'document'
                 WHERE a.posting_id = %s AND a.status = 'submitted'""", (pid,)).fetchall()}
    if not ids:
        raise HTTPException(409, "합격으로 고른 지원자가 없습니다")
    if ids - cur.keys():
        raise HTTPException(409, f"이 공고의 서류 심사 중인 지원자가 아닙니다: {sorted(ids - cur.keys())}")
    for i in ids:                                     # 먼저 모두 검사 (하나라도 안 되면 아무것도 바꾸지 않음)
        _check(db, i, "pass")
    for i, res in cur.items():
        if i in ids and res != "pass":
            _decide(db, i, "pass", admin)
        elif i not in ids and res == "pass":
            _decide(db, i, "hold", admin)


@router.post("/postings/{pid}/document/announce")
def announce_document(pid: int, body: AnnounceIn | None = None, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """1차 일괄 확정·발표 = 응시 안내 발송: 고른 사람(최근 결정 pass)은 합격, 나머지는 모두 불합격. 지원서 상태를 바꾸고 각자에게 알림.
    임시: 발표 전 검수(checked_by)는 별도 단계 없이 발표하는 사람이 함께 한 것으로 기록"""
    if body and body.pass_ids is not None:
        if _announced(db, pid):
            raise HTTPException(409, "이미 발표했습니다")
        _apply_picks(db, pid, set(body.pass_ids), admin)
    with db.transaction():
        if db.execute("SELECT 1 FROM job_posting WHERE id = %s FOR UPDATE", (pid,)).fetchone() is None:
            raise HTTPException(404, "공고가 없습니다")
        if _announced(db, pid):
            raise HTTPException(409, "이미 발표했습니다")
        apps = db.execute("""SELECT a.id, a.candidate_id, sr.result FROM application a
                             LEFT JOIN stage_result sr ON sr.application_id = a.id AND sr.stage = 'document'
                             WHERE a.posting_id = %s AND a.status = 'submitted'""", (pid,)).fetchall()
        if not apps:
            raise HTTPException(409, "서류 심사 중인 지원자가 없습니다")
        if not any(r["result"] == "pass" for r in apps):
            raise HTTPException(409, "합격으로 고른 지원자가 없습니다")
        n = db.execute("""INSERT INTO announcement(posting_id, stage, status, checked_by, published_by, published_at)
                          VALUES (%s, 'document', 'published', %s, %s, now())
                          ON CONFLICT (posting_id, stage) DO UPDATE SET status = 'published', checked_by = EXCLUDED.checked_by,
                              published_by = EXCLUDED.published_by, published_at = now()
                          RETURNING id""", (pid, admin["id"], admin["id"])).fetchone()
        sent = 0
        for r in apps:
            stage.ensure(db, r["id"])                    # 공통 상태를 바꾸기 전에 상세 단계를 고정
            passed = r["result"] == "pass"
            if not passed:                           # 고르지 않은 사람 = 불합격 (결정 기록도 남긴다)
                db.execute("""INSERT INTO stage_result(application_id, stage, result, reason, decided_by) VALUES (%s, 'document', 'fail', %s, %s)
                              ON CONFLICT (application_id, stage) DO UPDATE SET result = 'fail', reason = EXCLUDED.reason,
                                  decided_by = EXCLUDED.decided_by, decided_at = now()""",
                           (r["id"], "합격으로 고르지 않음 (일괄 확정)", admin["id"]))
            db.execute("UPDATE application SET status = %s WHERE id = %s", ("stage2" if passed else "doc_failed", r["id"]))
            sent += len(notify.send_result_ready(db, r["candidate_id"], n["id"], "doc_result_ready"))
    for r in apps:                                   # 상세 단계·메인 그래프 (발표가 끝난 뒤)
        if r["result"] == "pass":
            stage.path(db, r["id"], ["screen_passed", "coding_waiting", "scheduled"], actor_type="admin", actor_id=admin["id"])
            main_graph.advance(r["id"], "wait_invite", admin_id=admin["id"])     # 응시 안내 발송 → wait_invite 재개
        else:
            stage.move(db, r["id"], "screen_rejected", "admin", admin["id"])
            if main_graph.waiting(r["id"]) == "hr_screen":
                main_graph.advance(r["id"], "hr_screen", decision="reject", admin_id=admin["id"], reason="합격으로 고르지 않음 (일괄 확정)")
    return {"announced": len(apps), "passed": sum(r["result"] == "pass" for r in apps), "notifications": sent}


class RevokeIn(BaseModel):
    reason: str = Field(min_length=5, max_length=300)


@router.post("/applications/{app_id}/document/revoke")
def revoke_pass(app_id: int, body: RevokeIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """발표 뒤 1차 합격 취소: 부정행위(지원서와 지원자가 다름 등)를 발견한 경우만. 사유 필수, 결정자·시각 기록.
    최종 결정 전까지만. 진행 중인 면접이 있으면 담당자 중지로 끝낸다"""
    a = db.execute("SELECT status FROM application WHERE id = %s", (app_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "지원서가 없습니다")
    if a["status"] not in ("stage2", "stage2_done", "abandoned"):
        raise HTTPException(409, "1차 합격 뒤 최종 결정 전인 지원서만 합격을 취소할 수 있습니다")
    with db.transaction():
        stage.ensure(db, app_id)
        db.execute("""UPDATE stage_result SET result = 'fail', reason = %s, decided_by = %s, decided_at = now()
                      WHERE application_id = %s AND stage = 'document'""", (body.reason, admin["id"], app_id))
        db.execute("UPDATE application SET status = 'doc_failed' WHERE id = %s", (app_id,))
        db.execute("""UPDATE interview_session SET status = 'abandoned', ended_at = now(), end_reason = 'admin_stop'
                      WHERE application_id = %s AND status IN ('prechecked', 'in_progress', 'paused')""", (app_id,))
        db.execute("""INSERT INTO audit_log(actor_type, actor_id, action, target_type, target_id, detail)
                      VALUES ('admin', %s, 'screen_revoke', 'application', %s, %s)""",
                   (admin["id"], app_id, Jsonb({"decision": "revoke", "reason": body.reason})))
        stage.move(db, app_id, "screen_rejected", "admin", admin["id"], body.reason, strict=True)
    return {"revoked": True}


@router.get("/postings/{pid}/document/criteria")
def get_criteria(pid: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    return {"criteria": screen.criteria(db, pid)}


class CriteriaIn(BaseModel):
    items: list[str] = Field(max_length=30)


@router.put("/postings/{pid}/document/criteria")
def put_criteria(pid: int, body: CriteriaIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """1차 평가 기준(모두 우대) 바꾸기: 공고에 필요한 기술·경험을 적는다. AI 1차 검토 전까지만 (검토 결과와 어긋나지 않게)"""
    items = list(dict.fromkeys(x.strip()[:200] for x in body.items if x.strip()))
    if not items:
        raise HTTPException(422, "평가 기준을 하나 이상 적어 주세요")
    if _announced(db, pid) or db.execute("""SELECT 1 FROM document_evaluation d JOIN application a ON a.id = d.application_id
                                             WHERE a.posting_id = %s AND d.criteria_scores ? '결론'""", (pid,)).fetchone():
        raise HTTPException(409, "AI 1차 검토를 이미 실행해서 평가 기준을 바꿀 수 없습니다")
    with db.transaction():
        db.execute("DELETE FROM document_criteria WHERE posting_id = %s", (pid,))
        db.cursor().executemany("INSERT INTO document_criteria(posting_id, item, weight, description) VALUES (%s, %s, %s, '우대')",
                                [(pid, x, screen.CRIT_WEIGHT) for x in items])
        db.execute("""INSERT INTO audit_log(actor_type, actor_id, action, target_type, target_id, detail)
                      VALUES ('admin', %s, 'document_criteria', 'job_posting', %s, %s)""", (admin["id"], pid, Jsonb({"items": items})))
    return {"criteria": screen.criteria(db, pid)}
