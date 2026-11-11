"""DB 초기화(seed) 전에 직접 응시한 면접 기록을 꺼낸다 (포트폴리오 기록, 11/11). api 컨테이너에서 실행 → JSON을 표준 출력으로.
- 대상: 로그인할 수 있는 지원자(직접 확인용 계정)의 면접. 시험 데이터 시뮬레이션(로그인 불가 지원자)은 뺀다
- 담는 것: 응시 정보·모델, 물어본 순서대로 질문·근거·STT 글·답변 시간·판정 점수·모델·지연, 최종 평가 점수
- 개인정보: 이름은 담지 않고 지원 번호만. 음성·사진은 원래 저장하지 않음
실행: python scripts/export_sessions.py > 파일 (보통은 scripts/record_run.py export가 부른다)
"""
import json
import os
import sys

import psycopg
from psycopg.rows import dict_row


def main() -> int:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as db:
        sessions = db.execute("""SELECT s.id, s.application_id, s.attempt_no, s.status, s.end_reason, s.identity_status, s.ct_band,
                                        s.coding_weakness, s.llm_provider, s.llm_eval_model, s.llm_fast_model, s.llm_local_model,
                                        s.started_at, s.ended_at, p.title AS posting
                                 FROM interview_session s JOIN application a ON a.id = s.application_id
                                 JOIN candidate c ON c.id = a.candidate_id JOIN job_posting p ON p.id = a.posting_id
                                 WHERE c.password_hash IS NOT NULL AND s.started_at IS NOT NULL ORDER BY s.id""").fetchall()
        out = []
        for s in sessions:
            qs = db.execute("""SELECT q.ask_order, q.kind, q.question_type, q.depth, q.question_text, q.basis, q.generated_by_model,
                                      a.stt_text, a.stt_model, a.answer_sec, a.silence_ratio, a.no_response,
                                      j.score, j.status AS judge_status, j.model AS judge_model, j.latency_ms, j.opinion
                               FROM interview_question q LEFT JOIN interview_answer a ON a.question_id = q.id
                               LEFT JOIN answer_judgement j ON j.answer_id = a.id AND j.is_current
                               WHERE q.session_id = %s ORDER BY q.ask_order""", (s["id"],)).fetchall()
            ev = db.execute("""SELECT version_no, content_score, language_score, nonverbal_score, total_score, model, status
                               FROM interview_evaluation WHERE session_id = %s ORDER BY version_no DESC LIMIT 1""", (s["id"],)).fetchone()
            out.append({**s, "questions": qs, "evaluation": ev})
    json.dump(out, sys.stdout, ensure_ascii=False, default=str)
    return 0


if __name__ == "__main__":
    sys.exit(main())
