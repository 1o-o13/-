"""메일·문자 알림과 지원자 알림함 (F-ADM-19·46, F-CAN-18). 결과 내용은 보내지 않고 '발표됐으니 홈페이지에서 확인' 링크만 보낸다.
※ 임시: 메일 서버·문자 서비스 계정이 없어 실제로 보내지 않고 notification 행만 'sent'로 남긴다 (가짜 발송).
   실제 발송을 붙일 때는 _deliver() 한 곳만 바꾼다.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from api.auth import current_candidate
from api.db import get_db

router = APIRouter(prefix="/api/me")
log = logging.getLogger("notify")
STAGE = {"document": "1차 서류 전형", "final": "최종 전형"}


def _deliver(channel: str, to: str, template: str) -> bool:
    """가짜 발송: 로그만 남기고 성공으로 본다. 실제 발송(SMTP·문자 API)은 여기만 바꾼다"""
    log.info("가짜 발송 %s → %s (%s)", channel, to, template)
    return True


def send_result_ready(db, candidate_id: int, announcement_id: int, template: str) -> list[str]:
    """결과 발표 알림: 수신 설정(notification_pref, 없으면 둘 다 받음)에 맞춰 메일·문자를 보내고 기록. 보낸 채널 목록"""
    c = db.execute("""SELECT c.email, c.phone, coalesce(p.email, true) AS want_email, coalesce(p.sms, true) AS want_sms
                      FROM candidate c LEFT JOIN notification_pref p ON p.candidate_id = c.id WHERE c.id = %s""", (candidate_id,)).fetchone()
    sent = []
    for channel, to, want in (("email", c["email"], c["want_email"]), ("sms", c["phone"], c["want_sms"])):
        if not want:
            continue
        ok = _deliver(channel, to, template)
        db.execute("""INSERT INTO notification(candidate_id, channel, template, announcement_id, status, sent_at)
                      VALUES (%s, %s, %s, %s, %s, CASE WHEN %s THEN now() END)""",
                   (candidate_id, channel, template, announcement_id, "sent" if ok else "failed", ok))
        sent.append(channel)
    return sent


@router.get("/notifications")
def my_notifications(candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """알림함: 내가 지원한 공고의 발표된 결과 (최신 먼저). 읽음 표시는 화면이 기억한다 (임시: 읽음 칸이 DB에 없음)"""
    rows = db.execute("""SELECT n.id, n.stage, n.published_at, p.id AS posting_id, p.title
                         FROM announcement n JOIN job_posting p ON p.id = n.posting_id
                         JOIN application a ON a.posting_id = p.id AND a.candidate_id = %s
                         WHERE n.status IN ('published', 'corrected') ORDER BY n.published_at DESC""", (candidate_id,)).fetchall()
    return [{**r, "label": f"{STAGE[r['stage']]} 결과 발표"} for r in rows]


@router.get("/results/{pid}/document")
def document_result(pid: int, candidate_id: int = Depends(current_candidate), db=Depends(get_db, scope="function")):
    """1차(서류) 결과: 발표된 뒤에만. 합격이면 2차(코딩 테스트·AI 면접) 응시 기간을 알려 준다"""
    r = db.execute("""SELECT p.title, p.stage2_start, p.stage2_end, p.final_announce_at, n.published_at, sr.result
                      FROM application a JOIN job_posting p ON p.id = a.posting_id
                      JOIN announcement n ON n.posting_id = p.id AND n.stage = 'document' AND n.status IN ('published', 'corrected')
                      LEFT JOIN stage_result sr ON sr.application_id = a.id AND sr.stage = 'document'
                      WHERE a.posting_id = %s AND a.candidate_id = %s""", (pid, candidate_id)).fetchone()
    if r is None:
        raise HTTPException(404, "아직 발표된 결과가 없습니다")
    return {**r, "passed": r["result"] == "pass"}
