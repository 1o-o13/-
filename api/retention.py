"""면접 기록 보관 기간 (11/12 결정: 최종 발표 후 180일). 채용절차법의 채용서류 반환 청구 기간(최대 180일)에 맞춤.
지난 공고의 면접 기록을 지운다: 응시(interview_session)와 거기 딸린 질문·답변 STT 글·판정·최종 평가·본인 확인 결과·감독 이벤트·
메모·LLM 호출 기록(CASCADE), 면접 의심 건, 응시 편의 신청. 음성은 원래 STT 직후 지운다.
남기는 것: 2차 종합 점수(stage2_score, 공통 스키마 · 다른 파트 소유)와 지원서·증명사진(지원서 쪽 보관 규칙을 따름).
worker가 매일 한 번 부른다 (worker/app.py beat). 지운 건수는 audit_log에 남긴다 (내용 없이 숫자만)
"""
from psycopg.types.json import Jsonb

KEEP_DAYS = 180


def purge(db, keep_days: int = KEEP_DAYS) -> dict:
    apps = [r["id"] for r in db.execute("""SELECT a.id FROM application a JOIN job_posting p ON p.id = a.posting_id
                                           WHERE p.final_announce_at < now() - make_interval(days => %s)""", (keep_days,)).fetchall()]
    if not apps:
        return {"applications": 0, "sessions": 0}
    with db.transaction():
        db.execute("DELETE FROM suspicion_case WHERE stage = 'interview' AND application_id = ANY(%s)", (apps,))
        db.execute("DELETE FROM answer_accommodation WHERE application_id = ANY(%s)", (apps,))
        n = db.execute("DELETE FROM interview_session WHERE application_id = ANY(%s)", (apps,)).rowcount
        if n:
            db.execute("""INSERT INTO audit_log(actor_type, actor_id, action, target_type, target_id, detail)
                          VALUES ('system', NULL, 'interview_purge', 'application', NULL, %s)""",
                       (Jsonb({"sessions": n, "applications": len(apps), "keep_days": keep_days}),))
    return {"applications": len(apps), "sessions": n}
