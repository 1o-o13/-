"""지원자 면접 API (prefix /api/interview). 지원자 응답에는 점수·판정·본인 확인 결과를 넣지 않는다 (IV-02·43).

순서: guide(CAN-008) → precheck(응시 행 생성)·identity(CAN-009) → prepare(1~3번 준비, CAN-011) → start(설정 잠금)
      → state·events·answer·proctor·inquiry(CAN-012)
"""
import asyncio
import json
import os
import uuid
from typing import Literal

import psycopg
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.auth import current_candidate, own_application
from api.db import connect, get_db
from api import face
from api import stage

from api.interview import chatbot, engine, store, voice
from api.graph import interview as interview_graph
from api.graph import main as main_graph
from worker.tasks import process_answer, resume_reviewed

router = APIRouter(prefix="/api/interview")

LEAVE = ("tab_leave", "window_blur")
LEAVE_ABANDON_MS = 10_000          # 탭·창 이탈 한 번에 10초 이상이면 포기 (IV-30)
FACE_SUSPECT_MS = 5_000            # 얼굴 없음·시선 이탈 5초면 경고 + 의심 건 (IV-31)
RETAKES = 3                        # 본인 확인 재촬영 횟수 (IV-02)
VOICE_MIN_SEC = 0.5                # 임시: 녹음 중 소리가 난 시간이 이보다 짧으면 말을 안 한 것 (무응답)


@router.get("/applications")
def my_applications(candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """로그인한 지원자의 지원서만. 점수·판정은 넣지 않는다 (IV-43)"""
    return db.execute("""SELECT a.id, a.posting_id, p.title, a.status, p.stage2_start, p.stage2_end, p.final_announce_at, p.apply_end,
                                a.status = 'submitted' AND now() BETWEEN p.apply_start AND p.apply_end AS editable,
                                a.photo_object_key IS NOT NULL AS has_photo
                         FROM application a JOIN job_posting p ON p.id = a.posting_id
                         WHERE a.candidate_id = %s ORDER BY a.id""", (candidate_id,)).fetchall()


PHOTO_MAX = 5 * 1024 * 1024


@router.post("/applications/{app_id}/photo")
def upload_photo(app_id: int = Depends(own_application), photo: UploadFile = File(...), db=Depends(get_db, scope="function")):
    """증명사진 올리기·바꾸기 (본인 확인 얼굴 대조의 기준, 11/10). JPEG·PNG 5MB까지. 면접을 시작한 뒤에는 바꿀 수 없다.
    사진은 지원서 자료로 PHOTO_DIR에만 두고, 웹캠 프레임은 어디에도 저장하지 않는다"""
    data = photo.file.read(PHOTO_MAX + 1)
    if len(data) > PHOTO_MAX:
        raise HTTPException(413, "사진은 5MB까지 올릴 수 있습니다")
    ext = ".jpg" if data[:3] == bytes([0xFF, 0xD8, 0xFF]) else ".png" if data[:8] == bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) else None
    if ext is None:
        raise HTTPException(400, "JPEG·PNG 사진만 올릴 수 있습니다")
    if db.execute("""SELECT 1 FROM interview_session WHERE application_id = %s AND status IN ('in_progress', 'completed')""",
                  (app_id,)).fetchone():
        raise HTTPException(409, "면접을 시작한 뒤에는 사진을 바꿀 수 없습니다")
    key = f"{app_id}-{uuid.uuid4().hex}{ext}"
    os.makedirs(os.path.dirname(face.photo_path(key)), exist_ok=True)
    with open(face.photo_path(key), "wb") as f:
        f.write(data)
    old = db.execute("UPDATE application a SET photo_object_key = %s FROM application o WHERE a.id = o.id AND a.id = %s "
                     "RETURNING o.photo_object_key AS old", (key, app_id)).fetchone()["old"]
    if old and os.path.exists(face.photo_path(old)):
        os.remove(face.photo_path(old))
    return {"has_photo": True}


def own_session(sid: int, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")) -> int:
    row = db.execute("""SELECT a.candidate_id FROM interview_session s JOIN application a ON a.id = s.application_id
                        WHERE s.id = %s""", (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, "응시가 없습니다")
    if row["candidate_id"] != candidate_id:
        raise HTTPException(403, "본인 응시만 볼 수 있습니다")
    return sid


def _latest(db, app_id: int) -> dict | None:
    return db.execute("SELECT * FROM interview_session WHERE application_id = %s ORDER BY attempt_no DESC LIMIT 1",
                      (app_id,)).fetchone()


def _info(db, app_id: int) -> dict:
    return db.execute("""SELECT a.status, a.posting_id, p.title, p.job_category, p.stage2_start, p.stage2_end, p.final_announce_at,
                                now() BETWEEN p.stage2_start AND p.stage2_end AS in_window,
                                (SELECT c.status FROM coding_session c WHERE c.application_id = a.id
                                 ORDER BY c.attempt_no DESC LIMIT 1) AS coding_status,
                                st.total_questions, st.think_sec_non_tech, st.think_sec_tech, st.answer_max_sec, st.silence_skip_sec
                         FROM application a JOIN job_posting p ON p.id = a.posting_id
                         JOIN interview_setting st ON st.posting_id = p.id WHERE a.id = %s""", (app_id,)).fetchone()


def _blocked(info: dict, s: dict | None, coding: bool = True) -> str | None:
    """응시할 수 없는 이유. None이면 응시 가능. 코딩 테스트는 사전 점검·본인 확인 뒤에 보므로 안내·점검 단계에서는 coding=False"""
    if info["status"] != "stage2":
        return "2차 응시 대상이 아닙니다"
    if not info["in_window"]:
        return "응시 기간이 아닙니다"
    if coding and info["job_category"] == "dev" and info["coding_status"] != "completed":
        return "코딩 테스트를 마친 뒤 응시할 수 있습니다"          # IV-03
    if s and s["status"] in ("completed", "abandoned"):
        return "이미 응시를 마쳤습니다"
    if s and s["status"] in ("system_error", "paused"):
        return "응시가 멈췄습니다. 담당자 안내를 기다려 주세요"
    return None


def _need(s: dict | None, *statuses: str) -> dict:
    if s is None or s["status"] not in statuses:
        raise HTTPException(409, "지금 단계에서 할 수 없습니다")
    return s


def _has_photo(db, app_id: int) -> bool:
    return db.execute("SELECT photo_object_key IS NOT NULL AS ok FROM application WHERE id = %s", (app_id,)).fetchone()["ok"]


@router.get("/applications/{app_id}/guide")
def guide(app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    """CAN-008: 응시 기간·진행 순서·규칙, 응시 가능 여부"""
    info, s = _info(db, app_id), _latest(db, app_id)
    reason = _blocked(info, s, coding=False)
    steps = ["사전 점검·본인 확인·동의"] + (["코딩 테스트"] if info["job_category"] == "dev" else []) + ["안내", "AI 화상면접", "응시 완료"]
    return {"title": info["title"], "posting_id": info["posting_id"], "stage2_start": info["stage2_start"], "stage2_end": info["stage2_end"],
            "final_announce_at": info["final_announce_at"], "session_id": s["id"] if s else None,
            "exam_code": s["exam_code"] if s else None,
            "session_status": s["status"] if s else None, "can_start": reason is None,
            "coding_required": info["job_category"] == "dev", "coding_status": info["coding_status"], "reason": reason, "steps": steps,
            "face_real": face.model() == face.REAL, "has_photo": _has_photo(db, app_id),   # 실제 얼굴 대조면 증명사진이 있어야 본인 확인
            "rules": {k: info[k] for k in ("total_questions", "think_sec_non_tech", "think_sec_tech", "answer_max_sec",
                                           "silence_skip_sec")}}


class PrecheckIn(BaseModel):
    chrome: bool
    camera: bool
    mic: bool
    upload_mbps: float = Field(ge=0)
    single_face: bool
    consent_voice: bool          # 필수: 음성 녹음
    consent_ai: bool             # 필수: AI 활용
    consent_overseas: bool = False   # 필수: 국외 전송. 거부하면 응시 불가 — '거부 → 전부 사내 모델' 경로는 없음 (활동다이어그램 1109 5쪽, NFR-07)
    consent_face: bool = False   # 선택(별도 동의): 얼굴 생체정보 대조. 거부하면 촬영 없이 사람 확인 경로 (FR-02·03)


@router.post("/applications/{app_id}/precheck")
def precheck(body: PrecheckIn, app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    """CAN-009: 장치 점검·동의 기록. 첫 점검(또는 재응시 부여 뒤)이면 응시 행을 만들고 인계 데이터·코딩 약점·대역·모델을 복사한다"""
    info, s = _info(db, app_id), _latest(db, app_id)
    reason = _blocked(info, s, coding=False)
    if reason:
        raise HTTPException(409, reason)
    if not (body.chrome and body.camera and body.mic and body.single_face):
        raise HTTPException(400, "장치 점검을 통과해야 응시할 수 있습니다")
    if not (body.consent_voice and body.consent_ai and body.consent_overseas):
        raise HTTPException(400, "필수 동의 3가지(음성 녹음·AI 평가 활용·국외 전송)가 필요합니다")
    check = Jsonb(body.model_dump(include={"chrome", "camera", "mic", "upload_mbps", "single_face", "consent_face"}))
    if s and s["status"] in ("ready", "prechecked"):
        db.execute("""UPDATE interview_session SET precheck = %s, overseas_consent = %s, consent_at = now(), status = 'prechecked'
                      WHERE id = %s""", (check, body.consent_overseas, s["id"]))
        _face_refused(db, app_id, s["id"], body.consent_face)
        return {"session_id": s["id"], "exam_code": s["exam_code"]}
    if s and s["status"] != "retake_granted":
        raise HTTPException(409, "이미 응시 중입니다")
    attempt = s["attempt_no"] + 1 if s else 1
    src = db.execute("""SELECT cs.id AS coding_session_id, cr.weakness_summary, cr.q3_tier,
                               (SELECT d.handoff FROM document_evaluation d WHERE d.application_id = a.id AND d.handoff IS NOT NULL
                                ORDER BY d.version_no DESC LIMIT 1) AS handoff,
                               st.llm_provider, st.llm_eval_model, st.llm_fast_model, st.llm_local_model
                        FROM application a JOIN interview_setting st ON st.posting_id = a.posting_id
                        LEFT JOIN LATERAL (SELECT id FROM coding_session WHERE application_id = a.id AND status = 'completed'
                                           ORDER BY attempt_no DESC LIMIT 1) cs ON true
                        LEFT JOIN coding_result cr ON cr.session_id = cs.id
                        WHERE a.id = %s""", (app_id,)).fetchone()
    # 임시: 인계 데이터 위치 document_evaluation.handoff (팀 확정 전)
    row = db.execute("""INSERT INTO interview_session(application_id, attempt_no, exam_code, coding_session_id, coding_weakness, ct_band,
                            handoff, overseas_consent, status, precheck, consent_at, llm_provider, llm_eval_model, llm_fast_model,
                            llm_local_model)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'prechecked', %s, now(), %s, %s, %s, %s) RETURNING id, exam_code""",
                     (app_id, attempt, f"IV-{app_id:05d}-{attempt}", src["coding_session_id"],
                      Jsonb(src["weakness_summary"]) if src["weakness_summary"] else None,
                      engine.CT_BAND.get(src["q3_tier"]), Jsonb(src["handoff"]), body.consent_overseas, check,
                      src["llm_provider"], src["llm_eval_model"], src["llm_fast_model"], src["llm_local_model"])).fetchone()
    _face_refused(db, app_id, row["id"], body.consent_face)
    main_graph.advance(app_id, "wait_access")      # 코딩 없는 직군: 지원자 접속 = 사전 점검 (코딩 있는 직군은 코딩 시작 때)
    return {"session_id": row["id"], "exam_code": row["exam_code"]}


def _face_refused(db, app_id: int, sid: int, consent_face: bool) -> None:
    """얼굴 대조 거부 → 촬영 없이 '애매'로 두고 담당자 확인 의심 건을 연다 (자동 불합격 없음, 사람이 면접 기록으로 확인)"""
    if consent_face:
        return
    with db.transaction():
        done = db.execute("""UPDATE interview_session SET identity_status = 'unclear' WHERE id = %s AND identity_status IS NULL
                             RETURNING id""", (sid,)).fetchone()
        if done:
            db.execute("""INSERT INTO suspicion_case(stage, application_id, interview_session_id, reason, evidence)
                          VALUES ('interview', %s, %s, 'identity_unclear', %s)""",
                       (app_id, sid, Jsonb({"face_consent": False, "path": "사람 확인"})))


@router.post("/applications/{app_id}/identity")
def identity(app_id: int = Depends(own_application), frame: UploadFile = File(...), db=Depends(get_db, scope="function")):
    """CAN-009 본인 확인: 촬영할 때마다 지금 얼굴을 증명사진과 새로 대조한다 (이미 일치했어도 다시 찍으면 다시 대조, 11/10).
    거리·구간만 기록(사진 저장 안 함). 거리 ≤0.45 일치, ≤0.75 애매, 그 위 불일치 (api/face.py). 마지막 결과가 통과 여부.
    결과를 바로 알려 준다 (확인이 됐는지 모르고 넘어가지 않게. IV-02의 '결과 비공개'를 바꿈, 거리 값은 보이지 않음).
    result: match(통과) · retry(다시 촬영, left = 남은 횟수) · no_face(얼굴 못 찾음, 횟수에 안 넣음) ·
            failed(불일치 4번 = 처음 + 재촬영 3번 → 응시 막힘 + 의심 건) · skipped(얼굴 대조 거부 → 담당자 확인)"""
    s = _need(_latest(db, app_id), "prechecked")
    if not (s["precheck"] or {}).get("consent_face", True):
        return {"done": True, "result": "skipped"}
    fails = db.execute("""SELECT count(*) AS n FROM identity_check WHERE session_id = %s AND phase <> 'recheck'
                          AND band IN ('unclear', 'mismatch')""", (s["id"],)).fetchone()["n"]
    if fails > RETAKES:                              # 이미 실패로 막힘 (다시 찍어도 바뀌지 않음)
        return {"done": True, "result": "failed"}
    photo = db.execute("SELECT photo_object_key FROM application WHERE id = %s", (app_id,)).fetchone()["photo_object_key"]
    if photo is None and face.model() == face.REAL:   # 실제 대조는 증명사진이 있어야 한다 → 사진을 올리기 전에는 넘어가지 않음 (11/10)
        raise HTTPException(409, "증명사진이 없어 본인 확인을 할 수 없습니다. 증명사진을 먼저 올려 주세요")
    d = face.distance(frame.file.read(), photo)
    band = face.band(d)
    if band == "no_face":                            # 얼굴을 찾지 못한 촬영은 재촬영 횟수에 넣지 않는다 (조명·각도 문제, 11/10)
        return {"done": False, "result": "no_face"}
    first = not db.execute("SELECT 1 FROM identity_check WHERE session_id = %s", (s["id"],)).fetchone()
    with db.transaction():
        db.execute("INSERT INTO identity_check(session_id, phase, retake_no, distance, band, model) VALUES (%s, %s, %s, %s, %s, %s)",
                   (s["id"], "start" if first else "retake", min(fails, RETAKES), d, band, face.model()))
        if band == "match":
            db.execute("UPDATE interview_session SET identity_status = 'match' WHERE id = %s", (s["id"],))
            return {"done": True, "result": "match"}
        fails += 1
        if fails <= RETAKES:                         # 다시 찍어야 함: 앞서 일치했더라도 지금 얼굴이 다르면 통과를 거둔다
            db.execute("UPDATE interview_session SET identity_status = NULL WHERE id = %s", (s["id"],))
            return {"done": False, "result": "retry", "left": RETAKES + 1 - fails}
        result = "unclear" if band == "unclear" else "mismatch"
        db.execute("UPDATE interview_session SET identity_status = %s WHERE id = %s", (result, s["id"]))
        ids = [r["id"] for r in db.execute("SELECT id FROM identity_check WHERE session_id = %s", (s["id"],)).fetchall()]
        db.execute("""INSERT INTO suspicion_case(stage, application_id, interview_session_id, reason, evidence)
                      VALUES ('interview', %s, %s, %s, %s)""", (app_id, s["id"], f"identity_{result}", Jsonb({"identity_check_ids": ids})))
    return {"done": True, "result": "failed"}


@router.post("/sessions/{sid}/identity-recheck")
def identity_recheck(sid: int = Depends(own_session), frame: UploadFile = File(...), db=Depends(get_db, scope="function")):
    """면접 중 본인 확인 (60초마다 화면이 프레임 1장, 임시 간격). 거리·구간만 기록하고 사진은 저장하지 않는다.
    불일치면 감독 기록 + 의심 건(한 응시에 한 번). 자동 불합격 없음. 응답에 결과를 넣지 않는다.
    얼굴 대조에 동의하지 않았거나 (실제 대조인데) 증명사진이 없으면 기록하지 않는다"""
    s = db.execute("""SELECT s.status, s.precheck, s.application_id, a.photo_object_key FROM interview_session s
                      JOIN application a ON a.id = s.application_id WHERE s.id = %s""", (sid,)).fetchone()
    no_photo = s["photo_object_key"] is None and face.model() == face.REAL
    if s["status"] != "in_progress" or not (s["precheck"] or {}).get("consent_face", True) or no_photo:
        return {"recorded": False}
    d = face.distance(frame.file.read(), s["photo_object_key"])
    band = face.band(d)
    with db.transaction():
        db.execute("INSERT INTO identity_check(session_id, phase, retake_no, distance, band, model) VALUES (%s, 'recheck', 0, %s, %s, %s)",
                   (sid, d, band, face.model()))
        if band == "mismatch":
            n = db.execute("SELECT count(*) AS n FROM proctor_event WHERE session_id = %s AND event_type = 'identity_mismatch'",
                           (sid,)).fetchone()["n"] + 1
            db.execute("""INSERT INTO proctor_event(session_id, event_type, occurred_at, occurrence_no, action, meta)
                          VALUES (%s, 'identity_mismatch', now(), %s, 'suspected', %s)""", (sid, n, Jsonb({"distance": d})))
            if not db.execute("SELECT 1 FROM suspicion_case WHERE interview_session_id = %s AND reason = 'identity_mismatch'",
                              (sid,)).fetchone():
                db.execute("""INSERT INTO suspicion_case(stage, application_id, interview_session_id, reason, evidence)
                              VALUES ('interview', %s, %s, 'identity_mismatch', %s)""",
                           (s["application_id"], sid, Jsonb({"phase": "recheck", "distance": d})))
    return {"recorded": True}


@router.post("/applications/{app_id}/prepare")
def prepare(app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    """CAN-011 안내 화면에서 1~3번 질문을 미리 만든다 (이미 있으면 그대로)"""
    info, s = _info(db, app_id), _latest(db, app_id)
    reason = _blocked(info, s)
    if reason:
        raise HTTPException(409, reason)
    s = _need(s, "prechecked")
    why = store.identity_ok(s)
    if why:
        raise HTTPException(409, why)
    if not db.execute("SELECT 1 FROM interview_question WHERE session_id = %s", (s["id"],)).fetchone():
        # 코딩은 점검 뒤에 보므로, 질문을 만들기 직전에 마친 코딩 결과(약점·대역)를 응시에 복사한다 (3번 질문 입력)
        c = db.execute("""SELECT cs.id, cr.weakness_summary, cr.q3_tier FROM coding_session cs JOIN coding_result cr ON cr.session_id = cs.id
                          WHERE cs.application_id = %s AND cs.status = 'completed' ORDER BY cs.attempt_no DESC LIMIT 1""",
                       (app_id,)).fetchone()
        if c:
            db.execute("UPDATE interview_session SET coding_session_id = %s, coding_weakness = %s, ct_band = %s WHERE id = %s",
                       (c["id"], Jsonb(c["weakness_summary"]), engine.CT_BAND.get(c["q3_tier"]), s["id"]))
    # 메인 그래프 device_check(외부 대기 5) 재개 → 면접 그래프(S2) 시작: setup → 1~3번 준비 → 1번에서 멈춤.
    # 이미 시작했으면 그대로 (두 번 누름·새로고침)
    main_graph.advance(app_id, "device_check", session_id=s["id"])
    interview_graph.start(s["id"], app_id)
    return {"session_id": s["id"]}


@router.post("/applications/{app_id}/start")
def start(app_id: int = Depends(own_application), db=Depends(get_db, scope="function")):
    """면접 시작: 공고 설정 잠금, 설정의 모델을 응시에 고정, 1번 질문 표시"""
    info, s = _info(db, app_id), _latest(db, app_id)
    reason = _blocked(info, s)
    if reason:
        raise HTTPException(409, reason)
    s = _need(s, "prechecked")
    if db.execute("SELECT count(*) AS n FROM interview_question WHERE session_id = %s", (s["id"],)).fetchone()["n"] < 3:
        raise HTTPException(409, "질문 준비가 끝나지 않았습니다")
    with db.transaction():
        db.execute("UPDATE interview_setting SET locked_at = coalesce(locked_at, now()) WHERE posting_id = %s", (info["posting_id"],))
        db.execute("""UPDATE interview_session s SET status = 'in_progress', started_at = now(), llm_provider = st.llm_provider,
                          llm_eval_model = st.llm_eval_model, llm_fast_model = st.llm_fast_model, llm_local_model = st.llm_local_model
                      FROM interview_setting st WHERE st.posting_id = %s AND s.id = %s""", (info["posting_id"], s["id"]))
        db.execute("UPDATE interview_question SET asked_at = now() WHERE session_id = %s AND ask_order = 1", (s["id"],))
    stage.move(db, app_id, "interview", "candidate")                        # 상세 단계: 화상 면접
    return {"session_id": s["id"]}


@router.get("/sessions/{sid}/state")
def state(sid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """재접속 복구: 같은 문항·단계·남은 시간 (IV-32)"""
    return store.state(db, sid)


def _state_now(sid: int) -> dict:
    with connect() as db:
        return store.state(db, sid)


async def session_events(sid: int, poll_sec: float = 1.0):   # 50명+면 0.5초는 DB 조회가 초당 100번 (11/10)
    """SSE: 새 문항이 보이면 question, 답변 인식 글이 나오면 review, 끝나면 ended, 시스템 오류면 error를 보내고 닫는다"""
    last = None
    while True:
        st = await asyncio.to_thread(_state_now, sid)
        if st["status"] != "in_progress":
            yield {"event": "error" if st["status"] == "system_error" else "ended", "data": json.dumps(st, ensure_ascii=False)}
            return
        if st["question"] and st["question"]["id"] != last:
            last = st["question"]["id"]
            yield {"event": "question", "data": json.dumps(st, ensure_ascii=False)}
        rv = st.get("review")
        if rv and rv["ready"] and (rv["answer_id"], "review") != last:   # 답변 인식 글이 나옴 (11/11)
            last = (rv["answer_id"], "review")
            yield {"event": "review", "data": json.dumps(st, ensure_ascii=False)}
        await asyncio.sleep(poll_sec)


@router.get("/sessions/{sid}/events")
def events(sid: int = Depends(own_session)):
    return EventSourceResponse(session_events(sid))


@router.get("/sessions/{sid}/questions/{qid}/audio")
def question_audio(qid: int, sid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """질문 음성 (Supertonic, voice.py). 이미 물어본 이 응시의 질문만 (다음 질문을 미리 듣지 못하게).
    TTS_MODE=stub이거나 만들지 못하면 404 → 화면은 브라우저 음성·글로 진행 (IV-17)"""
    q = db.execute("SELECT question_text FROM interview_question WHERE id = %s AND session_id = %s AND asked_at IS NOT NULL",
                   (qid, sid)).fetchone()
    p = voice.make(qid, q["question_text"]) if q else None
    if p is None:
        raise HTTPException(404, "질문 음성이 없습니다")
    return FileResponse(p, media_type="audio/wav")


@router.post("/sessions/{sid}/questions/{qid}/answer", status_code=202)
def answer(qid: int, sid: int = Depends(own_session), audio: UploadFile = File(...), answer_sec: float = Form(ge=0),
           silence_ratio: float = Form(ge=0, le=1), finished_in_time: bool = Form(), upload_retry_count: int = Form(0, ge=0, le=3),
           voiced_sec: float | None = Form(None, ge=0), face_signals: str | None = Form(None), db=Depends(get_db, scope="function")):
    """답변 음성 업로드 → worker가 STT → 음성 삭제 → 판정 → 다음 질문. 지금 문항에만, 질문당 1번 (재녹음 없음, IV-20)
    voiced_sec: 화면이 잰 '소리가 난 시간'. 거의 없으면 음성을 버리고 무응답으로 (말 안 한 답변에 점수가 들어가지 않게)"""
    cur = store.state(db, sid)
    if cur["status"] != "in_progress" or not cur["question"] or cur["question"]["id"] != qid:
        raise HTTPException(409, "지금 답할 문항이 아닙니다")
    key = f"{uuid.uuid4().hex}.webm"
    with open(store.audio_path(key), "wb") as f:
        f.write(b"" if voiced_sec is not None and voiced_sec < VOICE_MIN_SEC else audio.file.read())
    try:
        aid = db.execute("""INSERT INTO interview_answer(question_id, answer_sec, finished_in_time, silence_ratio, audio_object_key,
                                upload_retry_count) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                         (qid, answer_sec, finished_in_time, silence_ratio, key, upload_retry_count)).fetchone()["id"]
    except psycopg.errors.UniqueViolation:
        os.remove(store.audio_path(key))
        raise HTTPException(409, "이미 답변을 냈습니다")
    store.save_face_signals(db, aid, face_signals)   # 녹음 중 표정 구간 (브라우저가 잰 수치만, 점수에 안 씀)
    process_answer.delay(aid)
    return {"accepted": True, "answer_id": aid}


class ConfirmIn(BaseModel):
    text: str | None = Field(None, max_length=5000)   # None = 인식 글 그대로


@router.post("/sessions/{sid}/answers/{aid}/confirm")
def confirm_answer(aid: int, body: ConfirmIn, sid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """답변 인식 글 확인·수정 '완료' (11/11) → 판정 → 다음 질문. 인식 오류를 고치는 정도만 (원본 대비 30% 이하).
    확인 시간이 지났거나 이미 확정한 답변은 거부 (시간이 지나면 원본 그대로 진행됨)"""
    rv = store.review(db, sid)
    if not rv or rv["answer_id"] != aid or not rv["ready"]:
        raise HTTPException(409, "확인할 답변이 아닙니다")
    if rv["remaining_sec"] <= 0:
        raise HTTPException(409, "확인 시간이 지나 인식된 글 그대로 제출됩니다")
    text = (body.text if body.text is not None else rv["text"]).strip()
    ratio = store.edit_ratio(rv["text"], text)
    if ratio > store.EDIT_MAX:
        raise HTTPException(422, f"인식이 틀린 부분만 고칠 수 있습니다 (지금 {round(ratio * 100)}% 바뀜, {round(store.EDIT_MAX * 100)}%까지)")
    if not text:
        raise HTTPException(422, "글을 모두 지울 수는 없습니다")
    if db.execute("""UPDATE interview_answer SET stt_text = %s, stt_edit_ratio = %s, stt_confirmed_at = now()
                     WHERE id = %s AND stt_confirmed_at IS NULL RETURNING id""", (text, ratio, aid)).fetchone() is None:
        raise HTTPException(409, "이미 제출된 답변입니다")
    resume_reviewed.delay(aid)
    return {"confirmed": True, "edited": ratio > 0}


class ProctorIn(BaseModel):
    event_type: Literal["tab_leave", "window_blur", "face_missing", "multi_face", "gaze_away", "network_drop", "reconnect", "upload_fail"]
    duration_ms: int = Field(ge=0)


@router.post("/sessions/{sid}/proctor")
def proctor(body: ProctorIn, sid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """감독 이벤트 (IV-30·31). 탭·창 이탈: 1번째 경고, 2번째이거나 10초 이상 포기.
    얼굴 없음·시선 이탈 5초 이상, 여러 명: 경고 + 의심 건 (자동 불합격 없음). 그 밖은 기록만"""
    cur = store.state(db, sid)
    if cur["status"] != "in_progress":
        raise HTTPException(409, "진행 중인 응시가 아닙니다")
    kinds = LEAVE if body.event_type in LEAVE else (body.event_type,)
    n = db.execute("SELECT count(*) AS n FROM proctor_event WHERE session_id = %s AND event_type = ANY(%s)",
                   (sid, list(kinds))).fetchone()["n"] + 1
    if body.event_type in LEAVE:
        action = "abandoned" if n >= 2 or body.duration_ms >= LEAVE_ABANDON_MS else "warned"
    elif body.event_type == "multi_face" or (body.event_type in ("face_missing", "gaze_away") and body.duration_ms >= FACE_SUSPECT_MS):
        action = "suspected"
    else:
        action = "logged"
    with db.transaction():
        eid = db.execute("""INSERT INTO proctor_event(session_id, event_type, occurred_at, duration_ms, occurrence_no, action, question_id)
                            VALUES (%s, %s, now(), %s, %s, %s, %s) RETURNING id""",
                         (sid, body.event_type, body.duration_ms, n, action,
                          cur["question"]["id"] if cur["question"] else None)).fetchone()["id"]
        if action == "suspected":
            db.execute("""INSERT INTO suspicion_case(stage, application_id, interview_session_id, reason, evidence)
                          SELECT 'interview', application_id, id, %s, %s FROM interview_session WHERE id = %s""",
                       (body.event_type, Jsonb({"proctor_event_ids": [eid]}), sid))
        if action == "abandoned":
            db.execute("""UPDATE interview_session SET status = 'abandoned', ended_at = now(), end_reason = 'tab_leave'
                          WHERE id = %s""", (sid,))
    return {"action": "warned" if action == "suspected" else action}    # 의심 건 여부는 지원자에게 알리지 않음


class ChatLine(BaseModel):
    role: Literal["user", "bot"]
    text: str = Field(min_length=1, max_length=1000)


class InquiryIn(BaseModel):
    messages: list[ChatLine] = Field(min_length=1, max_length=20)   # 지금까지 대화 (마지막이 응시자 말)
    stayed_sec: int = Field(ge=0, le=600)                            # 문의 창에 머문 시간 (화면이 잰 값)
    incident_id: int | None = None                                   # 같은 문의 창의 두 번째 말부터


@router.post("/sessions/{sid}/inquiry")
def inquiry(body: InquiryIn, sid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """문의하기 챗봇 (IV-33). 원인은 서버(챗봇·규칙)가 정한다. 시스템 원인이면 머문 시간만큼 지금 문항에 추가 시간(문의 창 하나에 한 번),
    응시자 원인·모름이면 0. 문의 창 하나 = interview_incident 한 줄"""
    s = db.execute("SELECT status, overseas_consent FROM interview_session WHERE id = %s", (sid,)).fetchone()
    if s["status"] != "in_progress":
        raise HTTPException(409, "진행 중인 응시가 아닙니다")
    events = [r["event_type"] for r in db.execute("""SELECT event_type FROM proctor_event WHERE session_id = %s
                                                     AND occurred_at > now() - interval '10 minutes' ORDER BY occurred_at""",
                                                  (sid,)).fetchall()]
    system_event = any(e in ("upload_fail", "network_drop") for e in events)
    cur = store.state(db, sid)
    context = (f"지금 {cur['question']['ask_order']}/{cur['total_questions']}번 문항, 단계 {cur['phase']}" if cur["question"] else "다음 질문 준비 중")
    context += f" / 최근 10분 기록: {', '.join(events) or '없음'}"
    out = chatbot.reply([m.model_dump() for m in body.messages], context, s["overseas_consent"], system_event)
    with db.transaction():
        if body.incident_id is None:
            inc = {"id": None, "cause": "unknown", "extra_time_sec": 0}
        else:
            inc = db.execute("SELECT id, cause, extra_time_sec FROM interview_incident WHERE id = %s AND session_id = %s",
                             (body.incident_id, sid)).fetchone()
            if inc is None:
                raise HTTPException(404, "문의가 없습니다")
        cause = "system" if "system" in (inc["cause"], out["cause"]) else out["cause"]   # 한 번 시스템 원인이면 그대로
        extra = inc["extra_time_sec"] or (body.stayed_sec if cause == "system" else 0)
        if inc["id"] is None:
            iid = db.execute("""INSERT INTO interview_incident(session_id, error_code, cause, chat_started_at, chat_ended_at,
                                    extra_time_sec, outcome)
                                VALUES (%s, 'CANDIDATE_INQUIRY', %s, now() - make_interval(secs => %s), now(), %s, 'resumed')
                                RETURNING id""", (sid, cause, body.stayed_sec, extra)).fetchone()["id"]
        else:
            iid = inc["id"]
            db.execute("UPDATE interview_incident SET cause = %s, extra_time_sec = %s, chat_ended_at = now() WHERE id = %s",
                       (cause, extra, iid))
        db.execute("UPDATE interview_session SET extra_time_sec = extra_time_sec + %s WHERE id = %s",
                   (extra - inc["extra_time_sec"], sid))
    return {"incident_id": iid, "reply": out["reply"], "cause": cause, "extra_time_sec": extra, "by": out["by"]}


@router.post("/sessions/{sid}/inquiry/{iid}/stop")
def inquiry_stop(iid: int, sid: int = Depends(own_session), db=Depends(get_db, scope="function")):
    """시스템 문제가 해결되지 않으면 면접을 멈추고 담당자에게 넘긴다 (담당자가 재응시를 줄 수 있음, IV-44)"""
    inc = db.execute("SELECT cause FROM interview_incident WHERE id = %s AND session_id = %s", (iid, sid)).fetchone()
    if inc is None or inc["cause"] != "system":
        raise HTTPException(409, "시스템 원인으로 확인된 문의만 면접을 멈출 수 있습니다")
    with db.transaction():
        db.execute("""UPDATE interview_session SET status = 'system_error', ended_at = now(), end_reason = 'system_error'
                      WHERE id = %s AND status = 'in_progress'""", (sid,))
        db.execute("UPDATE interview_incident SET outcome = 'stopped_reported', report_sent_at = now() WHERE id = %s", (iid,))
    return {"stopped": True}
