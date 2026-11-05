"""면접 worker 작업.
- process_answer: STT → 음성 삭제 → 면접 그래프(api/graph/interview.py) ask 재개 → 판정·다음 질문·종료·최종 평가는 그래프 노드가
  STT_MODE=real이면 stt 컨테이너(큐 'stt', faster-whisper)에 맡기고, 글이 오면 after_stt가 이어서 한다
"""
import logging
import os

from psycopg.types.json import Jsonb

from api.coding import q3, rules
from api.db import connect
from api.graph import interview as interview_graph
from api.interview import media_stub, store
from worker.app import celery


def _answer(db, answer_id: int) -> dict:
    return db.execute("""SELECT a.audio_object_key, a.silence_ratio, q.*, ap.resume_snapshot->>'시험용 수준' AS level
                         FROM interview_answer a JOIN interview_question q ON q.id = a.question_id
                         JOIN interview_session s ON s.id = q.session_id JOIN application ap ON ap.id = s.application_id
                         WHERE a.id = %s""", (answer_id,)).fetchone()


@celery.task
def process_answer(answer_id: int) -> None:
    with connect() as db:
        r = _answer(db, answer_id)
        path = store.audio_path(r["audio_object_key"])
        if os.environ.get("STT_MODE", "stub") == "stub":
            with open(path, "rb") as f:
                stt = media_stub.transcribe(f.read(), store.to_question(r).key_points, r["level"], float(r["silence_ratio"]))
            return _after_text(db, answer_id, stt, media_stub.STT_MODEL)
        # 빈 음성(화면이 잰 말한 시간이 거의 없음)이나 거의 침묵이면 STT 없이 무응답 (Whisper가 침묵에서 문장을 지어내지 않게)
        if os.path.getsize(path) == 0 or float(r["silence_ratio"]) >= media_stub.SILENT_RATIO:
            return _after_text(db, answer_id, None, "silence")
    # 질문별 용어 힌트 (11/12): 그 질문의 핵심어·기술 이름을 STT에 알려 준다 (stt/app.py의 회사 용어 힌트에 더함)
    q = store.to_question(r)
    hints = " ".join([*(q.key_points or []), q.tech_stack or ""]).strip()[:200]
    celery.send_task("stt.transcribe", args=[r["audio_object_key"], hints], queue="stt", link=after_stt.s(answer_id))


@celery.task
def after_stt(result: dict, answer_id: int) -> None:
    """stt 컨테이너의 결과를 받아 이어서: 음성 삭제 → 판정 → 다음 질문"""
    with connect() as db:
        if "error" in result:                               # 음성은 지우고 면접은 계속: 이 문항은 no_stt → 다음 주제 (활동다이어그램 1109)
            logging.getLogger(__name__).warning("STT 실패 answer=%s: %s", answer_id, result["error"])
            return _after_text(db, answer_id, None, "stt_failed", stt_failed=True)
        if result.get("segments"):
            store.save_voice_signals(db, answer_id, result["segments"])   # 목소리 표기 (점수에 안 씀)
            store.flag_voice_change(db, answer_id)                        # 앞 답변과 목소리 높이가 크게 다르면 참고 표기 (11/12)
        _after_text(db, answer_id, result["text"], result["model"])


def _after_text(db, answer_id: int, stt: str | None, stt_model: str, stt_failed: bool = False) -> None:
    """STT 글 저장·음성 삭제 → 지원자 확인(11/11) → 면접 그래프의 ask를 재개 (판정 → 다음 질문 → … 은 그래프가 한다).
    인식 글이 있으면 지원자에게 보여 주고 '완료'(api confirm)나 확인 시간이 지나면(stt_review_timeout) 재개한다.
    무응답·STT 실패는 확인할 글이 없어 바로 재개"""
    r = _answer(db, answer_id)
    os.remove(store.audio_path(r["audio_object_key"]))
    review = stt is not None and store.REVIEW_SEC > 0
    db.execute("""UPDATE interview_answer SET stt_text = %s, stt_original = %s, no_response = %s, stt_model = %s, audio_object_key = NULL,
                      audio_deleted_at = now(), stt_done_at = now(), stt_confirmed_at = CASE WHEN %s THEN NULL ELSE now() END
                  WHERE id = %s""",
               (stt, stt, stt is None, stt_model, review, answer_id))
    if review:
        stt_review_timeout.apply_async((answer_id,), countdown=store.REVIEW_SEC + 5)   # 화면을 닫아도 면접이 멈추지 않게
        return
    interview_graph.resume_answer(r["session_id"], answer_id, stt_failed)


@celery.task
def stt_review_timeout(answer_id: int) -> None:
    """확인 시간이 지나도록 '완료'가 없으면 인식 원본 그대로 확정하고 진행 (이미 확정했으면 아무것도 안 함)"""
    with connect() as db:
        if db.execute("""UPDATE interview_answer SET stt_confirmed_at = now() WHERE id = %s AND stt_confirmed_at IS NULL
                         RETURNING id""", (answer_id,)).fetchone():
            interview_graph.resume_answer(_answer(db, answer_id)["session_id"], answer_id)


@celery.task
def resume_reviewed(answer_id: int) -> None:
    """지원자가 확인(완료)한 답변으로 판정 → 다음 질문 (api confirm이 부른다)"""
    with connect() as db:
        interview_graph.resume_answer(_answer(db, answer_id)["session_id"], answer_id)


@celery.task
def screen_application(app_id: int) -> None:
    """AI 1차 검토: 메인 그래프 S0 (비교 검색 → LLM 의견 → 코드 검증) → 담당관 결정(hr_screen)에서 멈춤"""
    from api.graph import main as main_graph
    main_graph.start_s0(app_id)


@celery.task
def handoff_and_prepare(app_id: int) -> None:
    """1차 합격 뒤: handoff(면접 확인 필요 목록 + 결핍 가치, 1109 2쪽) → 2차 질문 미리 생성·검증"""
    from api import pregen, screen
    with connect() as db:
        screen.handoff(db, app_id)
        pregen.prepare(db, app_id)


@celery.task
def prepare_questions(app_id: int) -> None:
    """1차 합격 즉시: 1·2번 + 기술 본 질문 후보(4~10번)를 질문 은행에서 만들고 검증 (api/pregen.py)"""
    from api import pregen
    with connect() as db:
        pregen.prepare(db, app_id)


@celery.task
def prepare_q3_question(app_id: int) -> None:
    """코딩이 끝나는 즉시: 3번(코딩 약점 본 질문)을 만들고 검증"""
    from api import pregen
    with connect() as db:
        pregen.prepare_q3(db, app_id)


@celery.task
def prepare_q3(csid: int) -> None:
    """코딩 3번 준비: 1·2번 가장 좋은 제출로 등급·약점 → 출제(LLM·검증) 또는 대체 → 3번 배정 (CT-12~17)"""
    with connect() as db:
        if db.execute("SELECT 1 FROM coding_attempt WHERE session_id = %s AND slot = 3", (csid,)).fetchone():
            return
        att = db.execute("""SELECT a.id, p.type, (SELECT s.partial_score FROM coding_submission s WHERE s.attempt_id = a.id
                                                  ORDER BY s.partial_score DESC LIMIT 1) AS best,
                                   (SELECT s.case_results FROM coding_submission s WHERE s.attempt_id = a.id
                                    ORDER BY s.partial_score DESC LIMIT 1) AS cases
                            FROM coding_attempt a JOIN coding_problem p ON p.id = a.problem_id
                            WHERE a.session_id = %s AND a.slot IN (1, 2) ORDER BY a.slot""", (csid,)).fetchall()
        part = [float(a["best"] or 0) for a in att]
        tier = rules.q3_tier(*part)
        graded = [{"type": a["type"], "partial": float(a["best"] or 0), "case_results": a["cases"] or []} for a in att]
        pid, reason = q3.prepare(db, tier, rules.weakness(graded))
        db.execute("""INSERT INTO coding_attempt(session_id, slot, problem_id, language, assigned_reason)
                      VALUES (%s, 3, %s, 'python', %s) ON CONFLICT (session_id, slot) DO NOTHING""", (csid, pid, Jsonb(reason)))


@celery.task
def purge_expired_interviews() -> dict:
    """최종 발표 후 180일 지난 면접 기록 파기 (매일, worker/app.py beat)"""
    from api import retention
    with connect() as db:
        return retention.purge(db)
