"""11/12 화상면접 보완: 글로 답하기(사전 신청 + 담당관 승인) · 라이브니스 · 연습 면접 · 면접 기록 180일 파기"""
import psycopg
from psycopg.rows import dict_row

from api.test_interview_flow import OK_CHECK, answer, as_admin, as_candidate, begin, sql


def test_text_answer_needs_request_and_approval(client, db_url):
    app_id = as_candidate(client, 37)
    url = f"/api/interview/applications/{app_id}/accommodation"
    assert client.get(url).json() == {"request": None, "can_request": True}
    assert client.post(url, json={"reason": "짧"}).status_code == 422                       # 사유 5자 이상
    assert client.post(url, json={"reason": "언어 장애로 말하기가 어렵습니다"}).json() == {"status": "requested"}

    as_admin(client, "dev01")                                                              # 부서원은 조회만
    pid = sql(db_url, "SELECT posting_id FROM application WHERE id = %s", app_id)[0]["posting_id"]
    rows = client.get(f"/api/admin/accommodations?posting_id={pid}").json()
    xid = next(r["id"] for r in rows if r["application_id"] == app_id)
    assert client.post(f"/api/admin/accommodations/{xid}/decision", json={"approve": True}).status_code == 403
    as_admin(client, "hr01")
    assert client.post(f"/api/admin/accommodations/{xid}/decision", json={"approve": True}).json() == {"status": "approved"}

    _, sid = begin(client, 37)
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert st["answer_mode"] == "text"
    q1 = st["question"]
    r = client.post(f"/api/interview/sessions/{sid}/questions/{q1['id']}/answer-text",
                    json={"text": "결제 장애 때 로그를 먼저 확인하고 재시도 큐로 옮겼습니다.", "answer_sec": 40, "finished_in_time": True})
    assert r.status_code == 202
    assert client.post(f"/api/interview/sessions/{sid}/questions/{q1['id']}/answer-text",
                       json={"text": "다시", "answer_sec": 1, "finished_in_time": True}).status_code == 409   # 질문당 1번
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert st["phase"] == "think" and st["question"]["ask_order"] == 2                    # 인식 글 확인 없이 바로 다음 질문
    a = sql(db_url, "SELECT answer_mode, stt_text, stt_original, audio_object_key FROM interview_answer WHERE question_id = %s", q1["id"])[0]
    assert a == {"answer_mode": "text", "stt_text": "결제 장애 때 로그를 먼저 확인하고 재시도 큐로 옮겼습니다.", "stt_original": None, "audio_object_key": None}
    assert client.post(url, json={"reason": "면접 중 다시 신청합니다"}).status_code == 409      # 시작 뒤에는 신청 못 함

    as_admin(client, "hr01")
    q = next(x for x in client.get(f"/api/admin/interviews/{sid}").json()["questions"] if x["ask_order"] == 1)
    assert q["answer_mode"] == "text"                                                      # 리포트에 '글 답변' 표시


def test_text_answer_refused_without_approval(client):
    _, sid = begin(client, 38)
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert st["answer_mode"] == "voice"
    r = client.post(f"/api/interview/sessions/{sid}/questions/{st['question']['id']}/answer-text",
                    json={"text": "글로 답합니다", "answer_sec": 5, "finished_in_time": True})
    assert r.status_code == 403
    assert answer(client, sid, st["question"]["id"]).status_code == 202                    # 음성 답변은 그대로


def test_liveness_recorded_and_fail_opens_case(client, db_url):
    app_id = as_candidate(client, 39)
    url = f"/api/interview/applications/{app_id}/liveness"
    assert client.post(url, json={"passed": True}).status_code == 409                      # 사전 점검 전
    client.post(f"/api/interview/applications/{app_id}/precheck", json=OK_CHECK)
    client.post(f"/api/interview/applications/{app_id}/identity", files={"frame": ("f.jpg", b"jpeg", "image/jpeg")})
    assert client.post(url, json={"passed": False}).json() == {"ok": True}                 # 지원자에게 결과는 안 알림
    rows = sql(db_url, """SELECT i.liveness, c.reason FROM identity_check i JOIN interview_session s ON s.id = i.session_id
                          LEFT JOIN suspicion_case c ON c.interview_session_id = s.id WHERE s.application_id = %s""", app_id)
    assert rows == [{"liveness": "fail", "reason": "identity_unclear"}]                    # 막지 않고 담당관 확인용 의심 건


def test_practice_is_not_stored(client, db_url):
    app_id = as_candidate(client, 40)
    p = client.get(f"/api/interview/applications/{app_id}/practice").json()
    assert len(p["questions"]) == 2
    before = sql(db_url, "SELECT count(*) AS n FROM interview_answer")[0]["n"]
    r = client.post(f"/api/interview/applications/{app_id}/practice/stt", files={"audio": ("p.webm", b"voice", "audio/webm")})
    assert r.status_code == 200 and r.json()["text"]
    assert sql(db_url, "SELECT count(*) AS n FROM interview_answer")[0]["n"] == before    # 연습은 저장 안 함


def test_purge_after_180_days(client, db_url):
    """최종 발표 후 180일 지난 공고의 면접 기록을 지운다 (트랜잭션 안에서 확인하고 되돌림)"""
    from api import retention
    begin(client, 41)
    with psycopg.connect(db_url, row_factory=dict_row) as db:
        n0 = db.execute("SELECT count(*) AS n FROM interview_session").fetchone()["n"]
        assert n0 > 0
        assert retention.purge(db)["sessions"] == 0                                        # 발표 전·180일 안이면 그대로
        db.execute("""UPDATE job_posting SET apply_start = apply_start - interval '400 day', apply_end = apply_end - interval '400 day',
                          doc_announce_at = doc_announce_at - interval '400 day', stage2_start = stage2_start - interval '400 day',
                          stage2_end = stage2_end - interval '400 day', final_announce_at = final_announce_at - interval '400 day'""")
        r = retention.purge(db)
        assert r["sessions"] == n0
        assert db.execute("SELECT count(*) AS n FROM interview_answer").fetchone()["n"] == 0
        assert db.execute("SELECT detail FROM audit_log WHERE action = 'interview_purge'").fetchone()["detail"]["sessions"] == n0
        db.rollback()


def test_voice_change_flag(client, db_url):
    """앞 답변 2개 이상과 목소리 높이(f0) 중앙값이 35% 넘게 다르면 '다른 목소리 의심' 참고 표기 (점수에 안 씀)"""
    from api.db import connect
    from api.interview import store
    _, sid = begin(client, 42)
    ids = []
    for _ in range(3):
        st = client.get(f"/api/interview/sessions/{sid}/state").json()
        ids.append(answer(client, sid, st["question"]["id"]).json()["answer_id"])
        client.post(f"/api/interview/sessions/{sid}/answers/{ids[-1]}/confirm", json={})
    with connect() as db:
        for aid, f0 in zip(ids, (210, 205, 120)):          # 세 번째 답변만 목소리가 많이 낮음
            store.save_voice_signals(db, aid, [{"start": 0, "end": 3, "label": "차분한 목소리", "text": "답", "db": -20, "f0": f0, "cps": 5, "pause": 0}])
        assert store.flag_voice_change(db, ids[1]) is False   # 앞 답변 1개뿐 → 판단 안 함
        assert store.flag_voice_change(db, ids[2]) is True
    assert sql(db_url, "SELECT label FROM answer_signal WHERE answer_id = %s AND label = '다른 목소리 의심'", ids[2])
