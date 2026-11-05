"""관리자 면접 API (prefix /api/admin). 조회는 관리자 누구나, 설정·확정·재응시·메모·의심 건 처리는 쓰기 역할만 (auth.ADMIN_WRITE, 임시)."""
import os
from typing import Literal

import psycopg
import pyotp
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.auth import ADMIN_WRITE, current_admin
from api import notify, screen, stage

from api.db import get_db
from api.graph import interview as interview_graph
from api.graph import main as main_graph
from api.interview import engine, store

router = APIRouter(prefix="/api/admin")
READ = current_admin()
WRITE = current_admin(*ADMIN_WRITE)
MAX_ATTEMPT = 3                     # 재응시 최대 3차 (IV-44)


SUPER = current_admin("super_admin")


@router.get("/users/pending")
def pending_users(admin=Depends(SUPER), db=Depends(get_db, scope="function")):
    """승인 대기 관리자 (가입 신청)"""
    return db.execute("""SELECT u.id, u.login_id, u.name, u.role, d.name AS department, u.created_at FROM admin_user u
                         LEFT JOIN department d ON d.id = u.department_id WHERE NOT u.is_active ORDER BY u.id""").fetchall()


@router.post("/users/{uid}/approve")
def approve_user(uid: int, admin=Depends(SUPER), db=Depends(get_db, scope="function")):
    """승인 → 로그인 가능. 채용 담당은 2단계 인증이 필수라 비밀값을 만들어 한 번만 돌려준다 (본인이 인증 앱에 등록)
    임시: 비밀값은 평문 저장 (암호화 방식은 공통 기반 파트가 정함)"""
    u = db.execute("SELECT role FROM admin_user WHERE id = %s AND NOT is_active", (uid,)).fetchone()
    if u is None:
        raise HTTPException(409, "승인할 수 없는 계정입니다")
    secret = pyotp.random_base32() if u["role"] != "dept_member" else None
    db.execute("UPDATE admin_user SET is_active = true, totp_secret_enc = coalesce(%s, totp_secret_enc) WHERE id = %s",
               (secret, uid))
    return {"approved": True, "totp_secret": secret}


@router.post("/users/{uid}/reject")
def reject_user(uid: int, admin=Depends(SUPER), db=Depends(get_db, scope="function")):
    """거절 → 신청을 지운다 (승인 대기 계정만)"""
    if db.execute("DELETE FROM admin_user WHERE id = %s AND NOT is_active RETURNING id", (uid,)).fetchone() is None:
        raise HTTPException(409, "거절할 수 없는 계정입니다")
    return {"rejected": True}


@router.get("/postings")
def postings(admin=Depends(READ), db=Depends(get_db, scope="function")):
    """공고 목록 (면접 설정·응시 목록 화면에서 공고 고르기)"""
    # 지원자가 있는 공고가 먼저 (관리자 화면들이 첫 공고를 기본으로 연다)
    return db.execute("""SELECT id, title, status, stage2_start, stage2_end FROM job_posting p
                         ORDER BY (SELECT count(*) FROM application a WHERE a.posting_id = p.id) DESC, id DESC""").fetchall()


@router.post("/postings/{pid}/interview-setting/unlock")
def unlock_setting(pid: int, admin=Depends(SUPER), db=Depends(get_db, scope="function")):
    """개발 전용(DEV_QUICK_LOGIN=1), 최고관리자만: 시험 중 설정을 바꿀 수 있게 잠금을 푼다.
    지금 면접 중인 응시가 있으면 거부 (진행 중 응시는 시작 때 복사한 모델을 계속 쓰지만, 시간 규칙이 중간에 바뀌면 안 됨)"""
    if os.environ.get("DEV_QUICK_LOGIN") != "1":
        raise HTTPException(404)
    if db.execute("""SELECT 1 FROM interview_session s JOIN application a ON a.id = s.application_id
                     WHERE a.posting_id = %s AND s.status = 'in_progress'""", (pid,)).fetchone():
        raise HTTPException(409, "면접 중인 응시가 있어 잠금을 풀 수 없습니다")
    row = db.execute("UPDATE interview_setting SET locked_at = NULL WHERE posting_id = %s RETURNING *", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404, "면접 설정이 없습니다")
    return row


@router.get("/applications")
def applicants(posting_id: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """지원자 현황: 지원자별 인적사항 요약·1차 결과·코딩 등급·면접 상태 (이력서 원본은 관리자에게 그대로 보인다)"""
    rows = db.execute("""SELECT a.id, a.status, vs.stage, c.name, c.email, a.resume_snapshot->'인적사항'->>'성별' AS gender,
                                (a.resume_snapshot->'인적사항'->>'나이')::int AS age, a.resume_snapshot->>'시험용 수준' AS test_level,
                                d.status AS doc_status, d.criteria_scores->>'결론' AS ai_conclusion, d.handoff->>'deficit_value' AS deficit_value, cr.q3_tier,
                                (SELECT s.status FROM interview_session s WHERE s.application_id = a.id
                                 ORDER BY s.attempt_no DESC LIMIT 1) AS interview_status
                         FROM application a JOIN candidate c ON c.id = a.candidate_id
                         JOIN v_application_stage vs ON vs.application_id = a.id
                         LEFT JOIN LATERAL (SELECT * FROM document_evaluation WHERE application_id = a.id
                                            ORDER BY version_no DESC LIMIT 1) d ON true
                         LEFT JOIN LATERAL (SELECT r.* FROM coding_session cs JOIN coding_result r ON r.session_id = cs.id
                                            WHERE cs.application_id = a.id ORDER BY cs.attempt_no DESC LIMIT 1) cr ON true
                         WHERE a.posting_id = %s ORDER BY a.id""", (posting_id,)).fetchall()
    final = screen.final_conclusions(db, posting_id)  # 화면의 AI 추천 = 공고 상위 30% (1차 서류 화면과 같게, 11/12)
    return [r | {"ai_conclusion": final.get(r["id"])} for r in rows]


@router.get("/applications/{app_id}")
def applicant_detail(app_id: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """이력서 원본(인적사항 포함)·1차 결과·인계 데이터·코딩 결과"""
    a = db.execute("""SELECT a.id, a.status, a.resume_snapshot, a.submitted_at, p.title AS posting,
                             (SELECT s.id FROM interview_session s WHERE s.application_id = a.id ORDER BY s.attempt_no DESC LIMIT 1)
                               AS interview_session_id
                      FROM application a JOIN job_posting p ON p.id = a.posting_id WHERE a.id = %s""", (app_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "지원서가 없습니다")
    doc = db.execute("""SELECT version_no, criteria_scores, rationale, handoff, status FROM document_evaluation
                        WHERE application_id = %s ORDER BY version_no DESC LIMIT 1""", (app_id,)).fetchone()
    coding = db.execute("""SELECT cs.id AS session_id, r.p1, r.p2, r.q3_tier, r.q3_partial, r.q3_converted, r.weakness_summary FROM coding_session cs
                           JOIN coding_result r ON r.session_id = cs.id WHERE cs.application_id = %s
                           ORDER BY cs.attempt_no DESC LIMIT 1""", (app_id,)).fetchone()
    return {"application": a, "document": doc, "coding": coding}


@router.get("/postings/{pid}/interview-setting")
def get_setting(pid: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    row = db.execute("SELECT * FROM interview_setting WHERE posting_id = %s", (pid,)).fetchone()
    if row is None:
        raise HTTPException(404, "면접 설정이 없습니다")
    return row


class SettingIn(BaseModel):         # 범위·합계 규칙은 스키마 CHECK가 정답 (어기면 422)
    company_requirements: str | None = None
    total_questions: int
    followup_max_depth: int
    think_sec_non_tech: int
    think_sec_tech: int
    answer_max_sec: int
    silence_skip_sec: int
    follow_score: int
    retry_score: int
    weight_content: int
    weight_language: int
    weight_nonverbal: int
    llm_provider: str
    llm_eval_model: str
    llm_fast_model: str
    llm_local_model: str


@router.put("/postings/{pid}/interview-setting")
def put_setting(pid: int, body: SettingIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """ADM-025. 첫 응시가 시작되면 잠겨서 수정 거부 (IV-16)"""
    cols = list(SettingIn.model_fields)
    try:
        row = db.execute(f"""UPDATE interview_setting SET {", ".join(f"{c} = %s" for c in cols)}, updated_at = now()
                             WHERE posting_id = %s AND locked_at IS NULL RETURNING *""",
                         [getattr(body, c) for c in cols] + [pid]).fetchone()
    except psycopg.errors.CheckViolation as e:
        raise HTTPException(422, f"설정 값이 규칙에 맞지 않습니다 ({e.diag.constraint_name})")
    if row is None:
        if db.execute("SELECT 1 FROM interview_setting WHERE posting_id = %s", (pid,)).fetchone():
            raise HTTPException(409, "응시가 시작되어 설정이 잠겼습니다")
        raise HTTPException(404, "면접 설정이 없습니다")
    return row


@router.get("/interviews")
def list_interviews(posting_id: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """ADM-033 목록: 응시별 상태·최신 평가 총점·검증 상태·미결 의심 건 수"""
    return db.execute("""SELECT s.id, s.application_id, s.attempt_no, s.exam_code, s.status, s.end_reason, s.started_at, s.ended_at,
                                c.name AS candidate_name, e.version_no, e.total_score, e.status AS evaluation_status, e.confirmed_at,
                                (SELECT count(*) FROM suspicion_case sc
                                 WHERE sc.interview_session_id = s.id AND sc.status <> 'decided') AS open_suspicions
                         FROM interview_session s JOIN application a ON a.id = s.application_id JOIN candidate c ON c.id = a.candidate_id
                         LEFT JOIN LATERAL (SELECT * FROM interview_evaluation WHERE session_id = s.id
                                            ORDER BY version_no DESC LIMIT 1) e ON true
                         WHERE a.posting_id = %s ORDER BY s.id""", (posting_id,)).fetchall()


@router.get("/interviews/{sid}")
def interview_detail(sid: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """ADM-033 상세 (IV-42): 물어본 순서대로 질문·종류·근거 청크·STT·점수·루브릭·의견, 주제 점수·총점·5검사, 본인 확인·감독, 코딩 약점"""
    s = db.execute("""SELECT s.*, c.name AS candidate_name, a.posting_id, p.title AS posting_title, cr.q3_tier
                      FROM interview_session s JOIN application a ON a.id = s.application_id JOIN candidate c ON c.id = a.candidate_id
                      JOIN job_posting p ON p.id = a.posting_id LEFT JOIN coding_result cr ON cr.session_id = s.coding_session_id
                      WHERE s.id = %s""", (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "응시가 없습니다")
    questions = db.execute("""SELECT q.id, q.ask_order, q.kind, q.question_type, q.depth, q.tech_stack, q.parent_question_id,
                                     q.question_text, q.basis, q.source_doc_ids, q.min_tier, q.rag_check, q.defense, q.key_points,
                                     q.generated_by_model, q.asked_at,
                                     (SELECT coalesce(jsonb_agg(jsonb_build_object('chunk_id', d.doc || '#' || d.sec, 'doc_title', d.doc_title,
                                                                                    'sec_title', d.sec_title, 'tier', d.tier)), '[]')
                                      FROM company_doc_chunk d WHERE d.doc || '#' || d.sec IN
                                           (SELECT jsonb_array_elements_text(coalesce(q.source_doc_ids, '[]')))) AS sources,
                                     a.stt_text, a.stt_original, a.stt_edit_ratio, a.answer_mode, a.answer_sec, a.finished_in_time, a.silence_ratio, a.no_response, a.audio_deleted_at,
                                     j.status AS judge_status, j.score, j.rubric, j.opinion, j.quotes, j.rationale, j.lang_structure,
                                     j.lang_terms, j.lang_intent, j.model_tier, j.model AS judge_model, j.latency_ms,
                                     (SELECT coalesce(jsonb_agg(jsonb_build_object('source', g.source, 't0', g.t_start_ms, 't1', g.t_end_ms,
                                                                                    'label', g.label, 'value', g.value) ORDER BY g.t_start_ms, g.source), '[]')
                                      FROM answer_signal g WHERE g.answer_id = a.id) AS signals
                              FROM interview_question q LEFT JOIN interview_answer a ON a.question_id = q.id
                              LEFT JOIN answer_judgement j ON j.answer_id = a.id AND j.is_current
                              WHERE q.session_id = %s AND q.asked_at IS NOT NULL ORDER BY q.ask_order""", (sid,)).fetchall()
    evaluations = db.execute("""SELECT e.*, (SELECT jsonb_agg(c ORDER BY c.check_no) FROM evaluation_check c
                                             WHERE c.evaluation_id = e.id) AS checks
                                FROM interview_evaluation e WHERE e.session_id = %s ORDER BY e.version_no""", (sid,)).fetchall()
    def q(sql):
        return db.execute(sql, (sid,)).fetchall()
    st = db.execute("SELECT * FROM interview_setting WHERE posting_id = %s", (s["posting_id"],)).fetchone()
    judged = [{**x, "status": x["judge_status"], "score": None if x["score"] is None else float(x["score"]),
               "relevance": (x["rubric"] or {}).get(store.RELEVANCE)} for x in questions if x["judge_status"]]
    marks = engine.topic_marks(judged, st["total_questions"], st["follow_score"], st["retry_score"], st["followup_max_depth"]) if judged else []
    return {"session": s, "questions": questions, "evaluations": evaluations, "topic_marks": marks,
            "identity_checks": q("SELECT * FROM identity_check WHERE session_id = %s ORDER BY checked_at"),
            "llm_calls": q("""SELECT purpose, prompt_version, provider, model, min_tier, input_tokens, output_tokens, latency_ms, ok, route_note,
                                     created_at FROM llm_call WHERE session_id = %s ORDER BY id"""),
            "proctor_events": q("SELECT * FROM proctor_event WHERE session_id = %s ORDER BY occurred_at"),
            "suspicions": q("SELECT * FROM suspicion_case WHERE interview_session_id = %s ORDER BY id"),
            "incidents": q("SELECT * FROM interview_incident WHERE session_id = %s ORDER BY id"),
            "notes": q("SELECT * FROM interview_note WHERE session_id = %s ORDER BY id")}


@router.post("/interviews/{sid}/confirm")
def confirm(sid: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """검증을 통과한 최신 버전만 확정 (IV-41), 그 총점을 2차 종합 점수로 (IV-45). 코딩 점수 = coding_result.q3_converted"""
    with db.transaction():
        ev = db.execute("""SELECT id, total_score, confirmed_at FROM interview_evaluation WHERE session_id = %s AND status = 'passed'
                           ORDER BY version_no DESC LIMIT 1 FOR UPDATE""", (sid,)).fetchone()
        if ev is None:
            raise HTTPException(409, "검증을 통과한 평가가 없습니다")
        if ev["confirmed_at"]:
            raise HTTPException(409, "이미 확정했습니다")
        db.execute("UPDATE interview_evaluation SET confirmed_by = %s, confirmed_at = now() WHERE id = %s", (admin["id"], ev["id"]))
        score = db.execute("""INSERT INTO stage2_score(application_id, interview_score, coding_score)
                              SELECT s.application_id, %s, cr.q3_converted FROM interview_session s
                              LEFT JOIN coding_result cr ON cr.session_id = s.coding_session_id WHERE s.id = %s
                              ON CONFLICT (application_id) DO UPDATE SET interview_score = EXCLUDED.interview_score,
                                  coding_score = EXCLUDED.coding_score, computed_at = now()
                              RETURNING *""", (ev["total_score"], sid)).fetchone()
        rank_stage2(db, db.execute("SELECT a.posting_id FROM interview_session s JOIN application a ON a.id = s.application_id "
                                   "WHERE s.id = %s", (sid,)).fetchone()["posting_id"])
    interview_graph.resume_decision(sid, admin["id"])   # 면접 그래프 hr_decide(평가 확정) 재개 → 끝
    main_graph.advance(score["application_id"], "interview", session_id=sid)   # 메인 그래프: 2차 결과 확정 → 최종 선발 대기
    return {"evaluation_id": ev["id"], "stage2_score": score}


def rank_stage2(db, pid: int) -> None:
    """공고의 2차 종합 점수 순위·AI 추천을 다시 매긴다 (확정할 때마다).
    임시 규칙(팀 확정 전): 총점 높은 순, 과락이 아닌 사람 중 위에서 모집 인원의 2배까지 '합격 추천', 나머지 '추천 없음'.
    예비 합격은 두지 않는다 (11/10 결정: 넉넉하게 뽑아 다른 지원자를 거르는 방식)
    과락(면접 50 미만 또는 코딩 40 미만)은 순위만 매기고 추천하지 않는다 (DB 제약). 결정은 담당자가 한다"""
    rows = db.execute("""SELECT s.application_id, s.fail_cut FROM stage2_score s JOIN application a ON a.id = s.application_id
                         WHERE a.posting_id = %s ORDER BY s.total_score DESC, s.interview_score DESC, s.computed_at""", (pid,)).fetchall()
    head = db.execute("SELECT headcount FROM job_posting WHERE id = %s", (pid,)).fetchone()["headcount"]
    n = 0
    for rank, r in enumerate(rows, 1):
        rec = "none"
        if not r["fail_cut"]:
            n += 1
            rec = "pass" if n <= head * 2 else "none"
        db.execute("UPDATE stage2_score SET ai_rank = %s, ai_recommendation = %s WHERE application_id = %s", (rank, rec, r["application_id"]))


@router.get("/postings/{pid}/final")
def final_board(pid: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """ADM-042 최종 결정: 1차 합격자(2차 대상)를 2차 종합 점수 순으로. AI 추천·과락·담당자 결정, 아직 2차를 마치지 않은 사람은 아래에"""
    p = db.execute("SELECT id, title, headcount, final_announce_at FROM job_posting WHERE id = %s", (pid,)).fetchone()
    if p is None:
        raise HTTPException(404, "공고가 없습니다")
    rows = db.execute("""SELECT a.id, a.status, c.name, s.interview_score, s.coding_score, s.total_score, s.fail_cut, s.ai_rank,
                                s.ai_recommendation, cr.q3_tier, fr.reserve_rank, fr.decided_at, fa.name AS decided_by,
                                (SELECT count(*) FROM suspicion_case sc WHERE sc.application_id = a.id AND sc.status <> 'decided') AS open_suspicions,
                                EXISTS (SELECT 1 FROM notification n JOIN announcement x ON x.id = n.announcement_id
                                        WHERE x.posting_id = a.posting_id AND x.stage = 'final' AND n.candidate_id = a.candidate_id) AS announced,
                                (SELECT i.id FROM interview_session i WHERE i.application_id = a.id ORDER BY i.attempt_no DESC LIMIT 1) AS sid,
                                (SELECT i.status FROM interview_session i WHERE i.application_id = a.id ORDER BY i.attempt_no DESC LIMIT 1)
                                  AS interview_status,
                                (SELECT cs.status FROM coding_session cs WHERE cs.application_id = a.id ORDER BY cs.attempt_no DESC LIMIT 1)
                                  AS coding_status
                         FROM application a JOIN candidate c ON c.id = a.candidate_id
                         LEFT JOIN stage2_score s ON s.application_id = a.id
                         LEFT JOIN stage_result fr ON fr.application_id = a.id AND fr.stage = 'final'
                         LEFT JOIN admin_user fa ON fa.id = fr.decided_by
                         LEFT JOIN LATERAL (SELECT r.q3_tier FROM coding_session cs JOIN coding_result r ON r.session_id = cs.id
                                            WHERE cs.application_id = a.id ORDER BY cs.attempt_no DESC LIMIT 1) cr ON true
                         WHERE a.posting_id = %s AND a.status IN ('stage2', 'stage2_done', 'final_passed', 'reserve', 'final_failed')
                         ORDER BY s.ai_rank NULLS LAST, c.name""", (pid,)).fetchall()
    counts = db.execute("""SELECT count(*) AS total, count(*) FILTER (WHERE status = 'doc_failed') AS doc_failed,
                                  count(*) FILTER (WHERE status IN ('stage2', 'stage2_done', 'final_passed', 'reserve', 'final_failed')) AS doc_passed
                           FROM application WHERE posting_id = %s""", (pid,)).fetchone()
    ann = db.execute("""SELECT n.published_at, u.name AS published_by FROM announcement n LEFT JOIN admin_user u ON u.id = n.published_by
                        WHERE n.posting_id = %s AND n.stage = 'final' AND n.status IN ('published', 'corrected')""", (pid,)).fetchone()
    return {"posting": p, "counts": counts, "rows": rows, "announcement": ann}


class FinalIn(BaseModel):
    decision: Literal["final_passed", "final_failed"]   # 예비 합격 없음 (11/10)


@router.post("/applications/{app_id}/final")
def decide_final(app_id: int, body: FinalIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """담당자 최종 결정 (합격·불합격, 예비 없음 11/10) → 공통 stage_result(stage='final', 결정자)와 지원서 상태.
    2차 점수가 확정된 지원서만, 결과 발표 전까지 바꿀 수 있다 (임시: 발표 기능은 다른 파트).
    합격·예비는 DB 규칙(trg_final_decision)을 따른다: 과락 아님, 처리 안 된 의심 건 없음, 서류 합격 기록 있음"""
    return _final(db, app_id, body.decision, admin)


def _final(db, app_id: int, decision: str, admin: dict) -> dict:
    a = db.execute("""SELECT a.status, a.posting_id, s.application_id IS NOT NULL AS scored,
                             (SELECT r.reserve_rank FROM stage_result r WHERE r.application_id = a.id AND r.stage = 'final') AS reserve_rank
                      FROM application a LEFT JOIN stage2_score s ON s.application_id = a.id WHERE a.id = %s""", (app_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "지원서가 없습니다")
    if not a["scored"] or a["status"] not in ("stage2_done", "final_passed", "reserve", "final_failed"):
        raise HTTPException(409, "2차 점수가 확정된 지원자만 결정할 수 있습니다")
    if db.execute("""SELECT 1 FROM notification n JOIN announcement x ON x.id = n.announcement_id JOIN application ap ON ap.id = %s
                     WHERE x.posting_id = ap.posting_id AND x.stage = 'final' AND n.candidate_id = ap.candidate_id""", (app_id,)).fetchone():
        raise HTTPException(409, "최종 결과를 이미 알려서 바꿀 수 없습니다")
    result, rank = {"final_passed": "pass", "final_failed": "fail"}[decision], None
    try:
        with db.transaction():
            stage.ensure(db, app_id)
            db.execute("""INSERT INTO stage_result(application_id, stage, result, reserve_rank, decided_by) VALUES (%s, 'final', %s, %s, %s)
                          ON CONFLICT (application_id, stage) DO UPDATE SET result = EXCLUDED.result, reserve_rank = EXCLUDED.reserve_rank,
                              decided_by = EXCLUDED.decided_by, decided_at = now()""", (app_id, result, rank, admin["id"]))
            db.execute("UPDATE application SET status = %s WHERE id = %s", (decision, app_id))
        main_graph.advance(app_id, "final", admin_id=admin["id"])   # 메인 그래프: 사람 판단 2(최종 선발) → 끝
        stage.move(db, app_id, "final_pass" if result == "pass" else "final_fail", "admin", admin["id"])
    except psycopg.errors.CheckViolation as e:
        why = {"final_pass_with_fail_cut": "과락이라 합격·예비로 정할 수 없습니다",
               "final_pass_with_open_suspicion": "처리하지 않은 의심 건이 있습니다. 면접 결과에서 먼저 결정해 주세요",
               "final_without_document_pass": "서류 합격 기록이 없어 최종 결정을 할 수 없습니다",
               "final_without_stage2_score": "2차 점수가 확정된 지원자만 결정할 수 있습니다"}
        raise HTTPException(409, next((v for k, v in why.items() if k in str(e)), "DB 규칙에 맞지 않아 결정할 수 없습니다"))
    return {"status": decision, "reserve_rank": rank}


class FinalAnnounceIn(BaseModel):
    pass_ids: list[int]                               # 체크박스로 고른 최종 합격자 (11/11)


@router.post("/postings/{pid}/final/announce")
def announce_final(pid: int, body: FinalAnnounceIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """최종 결과 확정·발표 (11/11): 2차 점수가 확정된 지원자 중 체크한 사람은 합격, 나머지는 모두 불합격으로 정하고 각자에게 알림.
    이미 알림을 받은 지원자는 그대로 두고, 그 뒤에 2차 점수가 확정된 지원자는 다시 이 버튼으로 확정한다.
    합격은 DB 규칙(과락 아님·처리 안 된 의심 건 없음)을 따른다. 먼저 모두 검사하고, 하나라도 안 되면 아무것도 바꾸지 않는다"""
    rows = db.execute("""SELECT a.id, a.candidate_id, c.name, s.fail_cut,
                                (SELECT count(*) FROM suspicion_case sc WHERE sc.application_id = a.id AND sc.status <> 'decided') AS open_suspicions
                         FROM application a JOIN candidate c ON c.id = a.candidate_id JOIN stage2_score s ON s.application_id = a.id
                         WHERE a.posting_id = %s AND a.status IN ('stage2_done', 'final_passed', 'final_failed')
                           AND NOT EXISTS (SELECT 1 FROM notification n JOIN announcement x ON x.id = n.announcement_id
                                           WHERE x.posting_id = a.posting_id AND x.stage = 'final' AND n.candidate_id = a.candidate_id)
                         ORDER BY a.id""", (pid,)).fetchall()
    if not rows:
        raise HTTPException(409, "확정할 지원자가 없습니다 (2차 점수가 확정된 지원자만)")
    ids, by_id = set(body.pass_ids), {r["id"]: r for r in rows}
    if ids - by_id.keys():
        raise HTTPException(409, f"확정할 수 없는 지원자가 있습니다: {sorted(ids - by_id.keys())}")
    for i in ids:
        if by_id[i]["fail_cut"]:
            raise HTTPException(409, f"{by_id[i]['name']}: 과락이라 합격으로 정할 수 없습니다")
        if by_id[i]["open_suspicions"]:
            raise HTTPException(409, f"{by_id[i]['name']}: 처리하지 않은 의심 건이 있습니다. 면접 결과에서 먼저 결정해 주세요")
    for r in rows:
        _final(db, r["id"], "final_passed" if r["id"] in ids else "final_failed", admin)
    with db.transaction():
        n = db.execute("""INSERT INTO announcement(posting_id, stage, status, checked_by, published_by, published_at)
                          VALUES (%s, 'final', 'published', %s, %s, now())
                          ON CONFLICT (posting_id, stage) DO UPDATE SET status = 'published', checked_by = EXCLUDED.checked_by,
                              published_by = EXCLUDED.published_by, published_at = now()
                          RETURNING id""", (pid, admin["id"], admin["id"])).fetchone()
        sent = sum(len(notify.send_result_ready(db, r["candidate_id"], n["id"], "final_result_ready")) for r in rows)
    return {"announced": len(rows), "passed": len(ids), "notifications": sent}


@router.delete("/applications/{app_id}/final")
def cancel_final(app_id: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """최종 결정 취소 (같은 버튼을 다시 누름): 결정 기록을 지우고 2차 완료 상태로 되돌린다. 최종 발표 전까지만"""
    a = db.execute("SELECT posting_id, status FROM application WHERE id = %s", (app_id,)).fetchone()
    if a is None:
        raise HTTPException(404, "지원서가 없습니다")
    if a["status"] not in ("final_passed", "reserve", "final_failed"):
        raise HTTPException(409, "취소할 최종 결정이 없습니다")
    if db.execute("""SELECT 1 FROM announcement WHERE posting_id = %s AND stage = 'final' AND status IN ('published', 'corrected')""",
                  (a["posting_id"],)).fetchone():
        raise HTTPException(409, "최종 결과를 발표해서 취소할 수 없습니다")
    with db.transaction():
        stage.ensure(db, app_id)
        db.execute("DELETE FROM stage_result WHERE application_id = %s AND stage = 'final'", (app_id,))
        db.execute("UPDATE application SET status = 'stage2_done' WHERE id = %s", (app_id,))
    stage.move(db, app_id, "interview", "admin", admin["id"], "최종 결정 취소")
    return {"status": "stage2_done"}


@router.post("/interviews/{sid}/reattempt")
def reattempt(sid: int, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """재응시 부여. 다음 사전 점검 때 새 차수·새 질문으로 시작 (최대 3차)
    - 최고관리자·채용 담당: 장애로 멈춘 응시(system_error·paused)와 끝난 응시(completed·abandoned). 지원서는 2차 대상으로 되돌림
    - 임시: IV-44(채용 담당은 장애만)보다 넓힘 (11/9 사용자 요청)"""
    s = db.execute("SELECT attempt_no, status, application_id FROM interview_session WHERE id = %s", (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, "응시가 없습니다")
    if s["status"] not in ("system_error", "paused", "completed", "abandoned"):   # 쓰기 권한 관리자(최고관리자·채용 담당) 모두
        raise HTTPException(409, "끝났거나 장애로 멈춘 응시만 재응시를 줄 수 있습니다")
    if s["attempt_no"] >= MAX_ATTEMPT:
        raise HTTPException(409, f"재응시는 {MAX_ATTEMPT}차까지입니다")
    with db.transaction():
        db.execute("UPDATE interview_session SET status = 'retake_granted' WHERE id = %s", (sid,))
        db.execute("UPDATE application SET status = 'stage2' WHERE id = %s AND status = 'stage2_done'", (s["application_id"],))
    return {"next_attempt": s["attempt_no"] + 1}


@router.post("/interviews/{sid}/reset")
def reset_attempts(sid: int, admin=Depends(SUPER), db=Depends(get_db, scope="function")):
    """개발 전용(DEV_QUICK_LOGIN=1): 3차까지 다 쓴 뒤에도 면접을 계속 시험할 수 있게 이 지원서의 응시 기록을 모두 지운다.
    질문·답변·판정·평가·본인 확인·감독 기록·의심 건·2차 종합 점수까지 지우고 지원서를 2차 대상으로 되돌린다"""
    if os.environ.get("DEV_QUICK_LOGIN") != "1":
        raise HTTPException(404)
    row = db.execute("SELECT application_id FROM interview_session WHERE id = %s", (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, "응시가 없습니다")
    app_id = row["application_id"]
    with db.transaction():
        db.execute("""DELETE FROM ai_error_alert WHERE interview_evaluation_id IN (SELECT e.id FROM interview_evaluation e
                      JOIN interview_session s ON s.id = e.session_id WHERE s.application_id = %s)""", (app_id,))
        db.execute("DELETE FROM suspicion_case WHERE interview_session_id IN (SELECT id FROM interview_session WHERE application_id = %s)",
                   (app_id,))
        db.execute("DELETE FROM interview_session WHERE application_id = %s", (app_id,))   # 질문·답변·평가 등은 CASCADE
        db.execute("DELETE FROM stage2_score WHERE application_id = %s", (app_id,))
        db.execute("UPDATE application SET status = 'stage2' WHERE id = %s", (app_id,))
        rank_stage2(db, db.execute("SELECT posting_id FROM application WHERE id = %s", (app_id,)).fetchone()["posting_id"])
    return {"reset": True}


@router.get("/coding/{csid}")
def coding_detail(csid: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    """ADM-034 코딩 결과: 3번 환산 점수 먼저, 문항별 문제·배정 이유·정답 코드·가장 좋은 제출·그룹별 결과·코드 리뷰"""
    s = db.execute("""SELECT cs.id, cs.status, cs.started_at, cs.ended_at, cs.application_id, a.resume_snapshot->'인적사항'->>'이름' AS name,
                             p.title AS posting FROM coding_session cs JOIN application a ON a.id = cs.application_id
                      JOIN job_posting p ON p.id = a.posting_id WHERE cs.id = %s""", (csid,)).fetchone()
    if s is None:
        raise HTTPException(404, "코딩 응시가 없습니다")
    result = db.execute("SELECT * FROM coding_result WHERE session_id = %s", (csid,)).fetchone()
    items = db.execute("""SELECT a.id, a.slot, a.language, a.assigned_reason, a.started_at, a.ended_at, p.tier, p.type, p.origin, p.statement,
                                 p.solution_python, p.solution_java, p.time_limits,
                                 (SELECT count(*) FROM coding_submission x WHERE x.attempt_id = a.id) AS submissions,
                                 (SELECT coalesce(sum(x.paste_attempts), 0) FROM coding_submission x WHERE x.attempt_id = a.id) AS paste_attempts
                          FROM coding_attempt a JOIN coding_problem p ON p.id = a.problem_id WHERE a.session_id = %s ORDER BY a.slot""",
                       (csid,)).fetchall()
    for it in items:
        it["best"] = db.execute("""SELECT language, code, group_scores, partial_score, submitted_at FROM coding_submission
                                   WHERE attempt_id = %s ORDER BY partial_score DESC, submitted_at DESC LIMIT 1""", (it["id"],)).fetchone()
        it["review"] = db.execute("""SELECT rubric, summary, quality_level, model FROM coding_review WHERE attempt_id = %s
                                     ORDER BY created_at DESC LIMIT 1""", (it["id"],)).fetchone()
    return {"session": s, "result": result, "items": items}


@router.post("/coding/{csid}/reset")
def reset_coding(csid: int, admin=Depends(SUPER), db=Depends(get_db, scope="function")):
    """개발 전용(DEV_QUICK_LOGIN=1): 코딩 테스트를 처음부터 다시 볼 수 있게 이 응시를 지운다. 면접을 이미 시작했으면 거부"""
    if os.environ.get("DEV_QUICK_LOGIN") != "1":
        raise HTTPException(404)
    if db.execute("""SELECT 1 FROM interview_session WHERE coding_session_id = %s AND status NOT IN ('ready', 'prechecked')""",
                  (csid,)).fetchone():
        raise HTTPException(409, "이 코딩 결과로 면접을 이미 시작했습니다. 면접 기록부터 초기화해 주세요")
    with db.transaction():
        db.execute("UPDATE interview_session SET coding_session_id = NULL, coding_weakness = NULL, ct_band = NULL WHERE coding_session_id = %s",
                   (csid,))
        db.execute("DELETE FROM coding_session WHERE id = %s", (csid,))      # 문항·제출·리뷰·결과는 CASCADE
    return {"reset": True}


class NoteIn(BaseModel):
    body: str = Field(min_length=1)


@router.post("/interviews/{sid}/notes", status_code=201)
def add_note(sid: int, body: NoteIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    try:
        return db.execute("INSERT INTO interview_note(session_id, author_id, body) VALUES (%s, %s, %s) RETURNING *",
                          (sid, admin["id"], body.body)).fetchone()
    except psycopg.errors.ForeignKeyViolation:
        raise HTTPException(404, "응시가 없습니다")


class DecisionIn(BaseModel):
    decision: Literal["normal", "warning", "disqualified"]
    reason: str = Field(min_length=1)


@router.post("/suspicions/{case_id}/decision")
def decide_suspicion(case_id: int, body: DecisionIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    """면접 의심 건은 사람만 결정한다 (자동 불합격 없음, IV-31)"""
    row = db.execute("""UPDATE suspicion_case SET status = 'decided', decision = %s, decision_reason = %s, decided_by = %s,
                            decided_at = now() WHERE id = %s AND stage = 'interview' AND status <> 'decided' RETURNING *""",
                     (body.decision, body.reason, admin["id"], case_id)).fetchone()
    if row is None:
        raise HTTPException(409, "처리할 수 없는 의심 건입니다")
    return row
