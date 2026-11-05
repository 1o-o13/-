"""화상면접 보완 (11/12): 연습 면접 · 글로 답하기(응시 편의) · 라이브니스 결과.

- 연습 면접: 실제 화면과 같은 흐름(질문 음성 → 생각 → 녹음 → 인식 글 확인)을 질문 2개로. 평가·저장 없음 — 음성은 STT 뒤 바로 지우고 DB에 안 남김
- 글로 답하기: 말하기가 어려운 지원자가 응시 전에 신청(사유) → 담당관이 승인·거절 (사전 신청 + 승인, 11/12 결정).
  승인되면 면접 화면이 녹음 대신 글 입력. 답변 행은 answer_mode='text', 음성·STT 없이 바로 판정으로
- 라이브니스: 시작 전 본인 확인 때 1회 (11/12 결정). 브라우저가 고개 돌리기·눈 깜빡이기를 확인하고 결과만 보낸다 (영상 안 보냄)
"""
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from api.admin.routes import READ, WRITE
from api.auth import own_application
from api.db import get_db
from api.interview import store, voice
from api.interview.routes import own_session
from worker.tasks import resume_reviewed

router = APIRouter()
PRACTICE = ["연습 질문 1: 오늘 아침에 한 일을 30초 안에 말해 보세요.",
            "연습 질문 2: 최근에 새로 배운 기술 하나를 소개하고, 어디에 써 보고 싶은지 말해 보세요."]


# ---------- 연습 면접 ----------
@router.get("/api/interview/applications/{app_id}/practice")
def practice_questions(app_id: int = Depends(own_application)):
    return {"questions": PRACTICE, "think_sec": 10, "answer_max_sec": 40}


@router.get("/api/interview/applications/{app_id}/practice/{n}/audio")
def practice_audio(n: int, app_id: int = Depends(own_application)):
    """연습 질문 음성 (실제 질문과 같은 TTS). 만들지 못하면 404 → 화면은 글로"""
    if not 1 <= n <= len(PRACTICE):
        raise HTTPException(404, "연습 질문이 없습니다")
    p = voice.make(-n, PRACTICE[n - 1])            # 음수 번호: 실제 질문 번호와 겹치지 않게
    if p is None:
        raise HTTPException(404, "질문 음성이 없습니다")
    return FileResponse(p, media_type="audio/wav")


@router.post("/api/interview/applications/{app_id}/practice/stt")
def practice_stt(app_id: int = Depends(own_application), audio: UploadFile = File(...)):
    """연습 답변 → 인식 글만 돌려준다. 음성은 STT 뒤 바로 지우고, 글·점수는 어디에도 저장하지 않는다"""
    data = audio.file.read()
    if not data:
        return {"text": None}
    if os.environ.get("STT_MODE", "stub") == "stub":
        return {"text": "(연습) 오늘 아침에는 일찍 일어나 운동을 하고 면접을 준비했습니다."}
    from worker.app import celery
    key = f"practice-{uuid.uuid4().hex}.webm"
    with open(store.audio_path(key), "wb") as f:
        f.write(data)
    try:
        r = celery.send_task("stt.transcribe", args=[key, ""], queue="stt").get(timeout=90)
    except Exception:                                # noqa: BLE001  연습이라 실패해도 화면에 안내만
        r = {"error": "timeout"}
    finally:
        os.remove(store.audio_path(key))
    if "error" in r:
        raise HTTPException(503, "연습 답변을 글로 바꾸지 못했습니다. 실제 면접에는 영향이 없습니다")
    return {"text": r.get("text")}


# ---------- 글로 답하기 (응시 편의) ----------
class AccommodationIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _started(db, app_id: int) -> bool:
    return db.execute("""SELECT 1 FROM interview_session WHERE application_id = %s
                         AND status IN ('in_progress','paused','completed','abandoned','system_error')""", (app_id,)).fetchone() is not None


@router.get("/api/interview/applications/{app_id}/accommodation")
def my_accommodation(app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    r = db.execute("SELECT reason, status, decision_note, created_at, decided_at FROM answer_accommodation WHERE application_id = %s",
                   (app_id,)).fetchone()
    return {"request": r, "can_request": not _started(db, app_id)}


@router.post("/api/interview/applications/{app_id}/accommodation")
def request_accommodation(body: AccommodationIn, app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    """응시 전에만. 다시 신청하면 사유를 바꾸고 다시 '확인 중'으로"""
    if _started(db, app_id):
        raise HTTPException(409, "면접을 시작한 뒤에는 신청할 수 없습니다")
    db.execute("""INSERT INTO answer_accommodation(application_id, reason) VALUES (%s, %s)
                  ON CONFLICT (application_id) DO UPDATE SET reason = EXCLUDED.reason, status = 'requested', decided_by = NULL,
                      decided_at = NULL, decision_note = NULL, created_at = now()""", (app_id, body.reason.strip()))
    return {"status": "requested"}


@router.get("/api/admin/accommodations")
def list_accommodations(posting_id: int, admin=Depends(READ), db=Depends(get_db, scope="function")):
    return db.execute("""SELECT x.id, x.application_id, c.name, x.reason, x.status, x.decision_note, x.created_at, x.decided_at,
                                u.name AS decided_by
                         FROM answer_accommodation x JOIN application a ON a.id = x.application_id JOIN candidate c ON c.id = a.candidate_id
                         LEFT JOIN admin_user u ON u.id = x.decided_by WHERE a.posting_id = %s ORDER BY x.created_at""", (posting_id,)).fetchall()


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=300)


@router.post("/api/admin/accommodations/{xid}/decision")
def decide_accommodation(xid: int, body: DecisionIn, admin=Depends(WRITE), db=Depends(get_db, scope="function")):
    x = db.execute("SELECT application_id FROM answer_accommodation WHERE id = %s", (xid,)).fetchone()
    if x is None:
        raise HTTPException(404, "신청이 없습니다")
    if _started(db, x["application_id"]):
        raise HTTPException(409, "이미 면접을 시작해 바꿀 수 없습니다")
    db.execute("""UPDATE answer_accommodation SET status = %s, decided_by = %s, decided_at = now(), decision_note = %s WHERE id = %s""",
               ("approved" if body.approve else "rejected", admin["id"], body.note, xid))
    return {"status": "approved" if body.approve else "rejected"}


class TextAnswerIn(BaseModel):
    text: str = Field(max_length=5000)
    answer_sec: float = Field(ge=0)
    finished_in_time: bool


@router.post("/api/interview/sessions/{sid}/questions/{qid}/answer-text", status_code=202)
def answer_text(qid: int, body: TextAnswerIn, sid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """글로 답하기 (승인된 지원자만): 음성·STT·인식 글 확인 없이 쓴 글로 바로 판정 → 다음 질문. 빈 글은 무응답"""
    cur = store.state(db, sid)
    if cur["answer_mode"] != "text":
        raise HTTPException(403, "글로 답하기가 승인되지 않았습니다")
    if cur["status"] != "in_progress" or not cur["question"] or cur["question"]["id"] != qid:
        raise HTTPException(409, "지금 답할 문항이 아닙니다")
    text = body.text.strip() or None
    row = db.execute("""INSERT INTO interview_answer(question_id, answer_mode, stt_text, stt_model, answer_sec, finished_in_time, silence_ratio,
                            no_response, stt_done_at, stt_confirmed_at)
                        VALUES (%s, 'text', %s, 'text', %s, %s, 0, %s, now(), now())
                        ON CONFLICT (question_id) DO NOTHING RETURNING id""",
                     (qid, text, body.answer_sec, body.finished_in_time, text is None)).fetchone()
    if row is None:
        raise HTTPException(409, "이미 답변을 냈습니다")
    resume_reviewed.delay(row["id"])
    return {"accepted": True, "answer_id": row["id"]}


# ---------- 라이브니스 ----------
class LivenessIn(BaseModel):
    passed: bool


@router.post("/api/interview/applications/{app_id}/liveness")
def liveness(body: LivenessIn, app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    """시작 전 본인 확인(얼굴 대조)의 마지막 기록에 라이브니스 결과를 붙인다. 실패해도 막지 않고 담당관 확인용 의심 건으로"""
    s = db.execute("SELECT id FROM interview_session WHERE application_id = %s ORDER BY attempt_no DESC LIMIT 1", (app_id,)).fetchone()
    if s is None:
        raise HTTPException(409, "사전 점검을 먼저 해 주세요")
    ic = db.execute("""UPDATE identity_check SET liveness = %s WHERE id = (SELECT id FROM identity_check WHERE session_id = %s
                       AND phase IN ('start','retake') ORDER BY id DESC LIMIT 1) RETURNING id""",
                    ("pass" if body.passed else "fail", s["id"])).fetchone()
    if ic is None:
        raise HTTPException(409, "본인 확인 촬영을 먼저 해 주세요")
    if not body.passed and not db.execute("""SELECT 1 FROM suspicion_case WHERE interview_session_id = %s AND reason = 'identity_unclear'""",
                                          (s["id"],)).fetchone():
        from psycopg.types.json import Jsonb
        db.execute("""INSERT INTO suspicion_case(stage, application_id, interview_session_id, reason, evidence)
                      VALUES ('interview', %s, %s, 'identity_unclear', %s)""",
                   (app_id, s["id"], Jsonb({"liveness": "fail", "identity_check_id": ic["id"]})))
    return {"ok": True}          # 결과는 지원자에게 알리지 않는다 (IV-43)
