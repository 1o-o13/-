"""단계 3 검증 (stub 모드, worker는 eager): 면접 API로 처음부터 끝까지, 재접속, 감독, 설정 잠금, 시스템 오류·재응시, 확정.
지원자마다 다른 계정을 써서 시험끼리 섞이지 않게 한다. 실행: pytest -q -s api/test_interview_flow.py
"""
import asyncio
import json
import os
import time

import psycopg
import pyotp
from psycopg.rows import dict_row

from api.interview import media_stub, routes, store

PW = "Test1234!"
TOTP = "JBSWY3DPEHPK3PXP"
OK_CHECK = {"chrome": True, "camera": True, "mic": True, "upload_mbps": 12.5, "single_face": True,
            "consent_voice": True, "consent_face": True, "consent_ai": True, "consent_overseas": True}
FORM = {"answer_sec": "62.5", "silence_ratio": "0.1", "finished_in_time": "true"}


def sql(db_url, q, *a):
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as c:
        return c.execute(q, a).fetchall()


def has_score(obj) -> bool:
    """지원자 응답에 점수·판정·의견·본인 확인 결과가 섞였는지 (IV-02·43)"""
    if isinstance(obj, dict):
        return any(k in ("score", "rubric", "opinion", "total_score", "distance", "band", "identity_status") or has_score(v)
                   for k, v in obj.items())
    if isinstance(obj, list):
        return any(has_score(v) for v in obj)
    return False


def as_candidate(client, n: int) -> int:
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": f"cand{n:02d}@test.local", "password": PW}).status_code == 200
    return client.get("/api/interview/applications").json()[0]["id"]


def as_admin(client, login_id: str):
    client.cookies.clear()
    otp = pyotp.TOTP(TOTP).now() if login_id != "dev01" else None
    assert client.post("/api/auth/admin/login", json={"login_id": login_id, "password": PW, "otp": otp}).status_code == 200


def begin(client, n: int) -> tuple[int, int]:
    """cand n 로그인 → 안내 → 점검·동의 → 본인 확인 → 1~3번 준비 → 시작. (app_id, session_id)"""
    app_id = as_candidate(client, n)
    g = client.get(f"/api/interview/applications/{app_id}/guide").json()
    assert g["can_start"], g["reason"]
    assert client.post(f"/api/interview/applications/{app_id}/precheck", json=OK_CHECK).status_code == 200
    r = client.post(f"/api/interview/applications/{app_id}/identity", files={"frame": ("f.jpg", b"jpeg", "image/jpeg")})
    assert r.json() == {"done": True, "result": "match"}
    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 200
    r = client.post(f"/api/interview/applications/{app_id}/start")
    assert r.status_code == 200, r.text
    return app_id, r.json()["session_id"]


def answer(client, sid: int, qid: int, audio: bytes = b"voice", form=FORM):
    return client.post(f"/api/interview/sessions/{sid}/questions/{qid}/answer", files={"audio": ("a.webm", audio, "audio/webm")},
                       data=form)


def first_event(sid: int) -> dict:
    ev = asyncio.run(anext(routes.session_events(sid, poll_sec=0.01)))
    return {"event": ev["event"], **json.loads(ev["data"])}


def test_setting_put_then_locked(client, db_url):
    """ADM-025: 시작 전에는 수정되고 규칙 위반은 422, 첫 응시가 시작되면 잠겨서 거부 (IV-16)"""
    pid = sql(db_url, "SELECT id FROM job_posting")[0]["id"]
    sql(db_url, "UPDATE interview_setting SET locked_at = NULL WHERE posting_id = %s RETURNING posting_id", pid)   # 앞 시험 파일이 응시를 시작했을 수 있음
    as_admin(client, "hr01")
    cur = client.get(f"/api/admin/postings/{pid}/interview-setting").json()
    assert cur["locked_at"] is None
    body = {k: cur[k] for k in ("company_requirements", "total_questions", "followup_max_depth", "think_sec_non_tech", "think_sec_tech",
                                "answer_max_sec", "silence_skip_sec", "follow_score", "retry_score", "weight_content",
                                "weight_language", "weight_nonverbal", "llm_provider", "llm_eval_model", "llm_fast_model",
                                "llm_local_model")}
    assert client.put(f"/api/admin/postings/{pid}/interview-setting", json={**body, "retry_score": 80}).status_code == 422
    assert client.put(f"/api/admin/postings/{pid}/interview-setting",
                      json={**body, "company_requirements": "결제 장애 대응 경험"}).status_code == 200
    as_admin(client, "dev01")
    assert client.put(f"/api/admin/postings/{pid}/interview-setting", json=body).status_code == 403     # 부서원은 조회만
    begin(client, 10)
    as_admin(client, "hr01")
    r = client.put(f"/api/admin/postings/{pid}/interview-setting", json=body)
    assert r.status_code == 409
    assert client.get(f"/api/admin/postings/{pid}/interview-setting").json()["locked_at"] is not None


def test_full_interview_then_confirm(client, db_url):
    """cand01: 시작 → 10문항 → 종료(stage2_done) → 평가 v1 검증 통과 → hr01 확정 → stage2_score"""
    app_id, sid = begin(client, 1)
    seen, slowest = [], 0.0
    while True:
        st = client.get(f"/api/interview/sessions/{sid}/state").json()
        assert not has_score(st)
        if st["phase"] == "ended":
            break
        assert st["phase"] == "think"
        qid = st["question"]["id"]
        seen.append((st["question"]["ask_order"], st["question"]["kind"], st["question"]["question_type"]))
        t0 = time.monotonic()
        r = answer(client, sid, qid)
        assert r.status_code == 202 and not has_score(r.json())
        nxt = client.get(f"/api/interview/sessions/{sid}/state").json()
        slowest = max(slowest, time.monotonic() - t0)
        assert nxt["phase"] in ("think", "ended")                          # 준비 중으로 멈추지 않음
        assert answer(client, sid, qid).status_code == 409                 # 재녹음 없음
    assert [o for o, _, _ in seen] == list(range(1, 11))
    assert [k for _, k, _ in seen] == ["non_tech"] * 2 + ["tech"] * 8
    assert slowest < 5, f"답변 → 다음 질문 {slowest:.2f}초"
    assert first_event(sid)["event"] == "ended"

    s = sql(db_url, "SELECT status, end_reason FROM interview_session WHERE id = %s", sid)[0]
    assert (s["status"], s["end_reason"]) == ("completed", "finished")
    assert sql(db_url, "SELECT status FROM application WHERE id = %s", app_id)[0]["status"] == "stage2_done"
    audio = sql(db_url, """SELECT count(*) FILTER (WHERE audio_object_key IS NULL AND audio_deleted_at IS NOT NULL AND stt_done_at IS NOT NULL) AS gone,
                                  count(*) AS n FROM interview_answer a JOIN interview_question q ON q.id = a.question_id
                           WHERE q.session_id = %s""", sid)[0]
    assert audio["gone"] == audio["n"] == 10 and os.listdir(os.environ["AUDIO_DIR"]) == []   # 음성은 STT 뒤 모두 삭제
    ev = sql(db_url, "SELECT id, version_no, status, total_score FROM interview_evaluation WHERE session_id = %s", sid)
    assert [(e["version_no"], e["status"]) for e in ev] == [(1, "passed")]
    assert sql(db_url, "SELECT count(*) AS n FROM evaluation_check WHERE evaluation_id = %s AND passed", ev[0]["id"])[0]["n"] == 5
    assert client.get(f"/api/interview/applications/{app_id}/guide").json()["can_start"] is False

    as_admin(client, "dev01")
    assert client.post(f"/api/admin/interviews/{sid}/confirm").status_code == 403
    as_admin(client, "hr01")
    detail = client.get(f"/api/admin/interviews/{sid}").json()
    assert [q["ask_order"] for q in detail["questions"]] == list(range(1, 11))
    assert all(q["stt_text"] and q["rationale"] for q in detail["questions"])
    assert all(q["sources"] for q in detail["questions"] if q["kind"] == "tech")      # 기술 질문은 근거 청크가 있음
    assert detail["session"]["coding_weakness"]["algorithms"]
    listed = client.get("/api/admin/interviews", params={"posting_id": detail["session"]["posting_id"]}).json()
    assert any(x["id"] == sid and x["evaluation_status"] == "passed" for x in listed)
    r = client.post(f"/api/admin/interviews/{sid}/confirm")
    assert r.status_code == 200, r.text
    score = sql(db_url, """SELECT s.interview_score, s.coding_score FROM stage2_score s WHERE s.application_id = %s""", app_id)[0]
    coding = sql(db_url, """SELECT cr.q3_converted FROM coding_result cr JOIN coding_session cs ON cs.id = cr.session_id
                            WHERE cs.application_id = %s""", app_id)[0]["q3_converted"]
    assert score["interview_score"] == ev[0]["total_score"] and score["coding_score"] == coding
    assert client.post(f"/api/admin/interviews/{sid}/confirm").status_code == 409                 # 두 번 확정 없음
    print(f"\n  cand01 10문항 {seen}\n  답변 → 다음 질문 최대 {slowest:.3f}초, 면접 {score['interview_score']} · 코딩 {coding}")


def test_reconnect_same_question(client):
    """새로고침·재접속하면 같은 문항·같은 단계 (IV-32), 남의 응시는 403"""
    _, sid = begin(client, 2)
    a, b = (client.get(f"/api/interview/sessions/{sid}/state").json() for _ in range(2))
    assert a["question"]["id"] == b["question"]["id"] and a["question"]["ask_order"] == 1
    assert b["remaining_sec"] <= a["remaining_sec"]
    assert first_event(sid)["question"]["id"] == a["question"]["id"]
    answer(client, sid, a["question"]["id"])
    c, d = (client.get(f"/api/interview/sessions/{sid}/state").json() for _ in range(2))
    assert c["question"]["ask_order"] == d["question"]["ask_order"] == 2 and c["question"]["id"] == d["question"]["id"]
    as_candidate(client, 11)
    assert client.get(f"/api/interview/sessions/{sid}/state").status_code == 403


def test_tab_leave_twice_abandons(client, db_url):
    _, sid = begin(client, 3)
    p = f"/api/interview/sessions/{sid}/proctor"
    assert client.post(p, json={"event_type": "tab_leave", "duration_ms": 2000}).json()["action"] == "warned"
    assert client.post(p, json={"event_type": "window_blur", "duration_ms": 1000}).json()["action"] == "abandoned"
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert (st["status"], st["phase"]) == ("abandoned", "ended")
    assert answer(client, sid, 1).status_code == 409
    assert sql(db_url, "SELECT end_reason FROM interview_session WHERE id = %s", sid)[0]["end_reason"] == "tab_leave"


def test_tab_leave_10s_abandons_at_once(client):
    _, sid = begin(client, 4)
    r = client.post(f"/api/interview/sessions/{sid}/proctor", json={"event_type": "tab_leave", "duration_ms": 10_000})
    assert r.json()["action"] == "abandoned"


def test_face_events_warn_and_suspect(client, db_url):
    """얼굴 없음 5초 미만은 기록만, 5초 이상·여러 명은 경고 + 의심 건. 응시는 계속 (자동 불합격 없음)"""
    _, sid = begin(client, 5)
    p = f"/api/interview/sessions/{sid}/proctor"
    assert client.post(p, json={"event_type": "face_missing", "duration_ms": 3000}).json()["action"] == "logged"
    assert client.post(p, json={"event_type": "face_missing", "duration_ms": 5000}).json()["action"] == "warned"
    assert client.post(p, json={"event_type": "multi_face", "duration_ms": 0}).json()["action"] == "warned"
    assert client.get(f"/api/interview/sessions/{sid}/state").json()["status"] == "in_progress"
    cases = sql(db_url, "SELECT id, reason FROM suspicion_case WHERE interview_session_id = %s ORDER BY id", sid)
    assert [c["reason"] for c in cases] == ["face_missing", "multi_face"]
    as_admin(client, "hr01")
    r = client.post(f"/api/admin/suspicions/{cases[0]['id']}/decision", json={"decision": "normal", "reason": "조명 문제"})
    assert r.status_code == 200
    assert client.post(f"/api/admin/suspicions/{cases[0]['id']}/decision",
                       json={"decision": "warning", "reason": "x"}).status_code == 409
    assert client.post(f"/api/admin/interviews/{sid}/notes", json={"body": "조명 확인함"}).status_code == 201


def test_judge_error_does_not_stop_interview_then_reattempt(client, db_url, monkeypatch):
    """판정 모델 오류 → 면접은 멈추지 않고 점수 보류(parse_error, NULL)로 다음 문항 (활동다이어그램 1109).
    장애로 멈춘 응시는 담당자 재응시(새 차수·새 질문) → 최대 3차"""
    from api import modules as M

    def broken(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(M, "judge_answer", broken)
    app_id, sid = begin(client, 6)
    qid = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]["id"]
    answer(client, sid, qid)
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert st["status"] == "in_progress" and st["question"]["ask_order"] == 2
    j = sql(db_url, """SELECT j.status, j.score, j.rationale FROM answer_judgement j JOIN interview_answer a ON a.id = j.answer_id
                       WHERE a.question_id = %s""", qid)[0]
    assert (j["status"], j["score"]) == ("parse_error", None) and "보류" in j["rationale"]
    monkeypatch.undo()
    for attempt in (1, 2, 3):
        if attempt > 1:
            app_id, sid = begin(client, 6)
        sql(db_url, "UPDATE interview_session SET status = 'system_error', ended_at = now(), end_reason = 'system_error' "
                    "WHERE id = %s RETURNING id", sid)        # 서버 장애 등으로 멈춘 응시
        as_admin(client, "hr01")
        r = client.post(f"/api/admin/interviews/{sid}/reattempt")
        if attempt < 3:
            assert r.json() == {"next_attempt": attempt + 1}
        else:
            assert r.status_code == 409                       # 4차 없음
    rows = sql(db_url, "SELECT attempt_no, status FROM interview_session WHERE application_id = %s ORDER BY attempt_no", app_id)
    assert [(r["attempt_no"], r["status"]) for r in rows] == [(1, "retake_granted"), (2, "retake_granted"), (3, "system_error")]


def test_silent_tech_answer_scores_zero(client, db_url):
    """응답 상태가 ok가 아니면(빈 음성 = 무응답) 기술 질문 0점, 다음 주제로 (IV-21)"""
    _, sid = begin(client, 7)
    for _ in range(2):
        answer(client, sid, client.get(f"/api/interview/sessions/{sid}/state").json()["question"]["id"])
    q3 = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]
    assert q3["kind"] == "tech"
    answer(client, sid, q3["id"], audio=b"", form={**FORM, "silence_ratio": "1", "answer_sec": "5"})
    j = sql(db_url, """SELECT a.no_response, a.stt_text, j.status, j.score FROM interview_answer a JOIN answer_judgement j ON j.answer_id = a.id
                       WHERE a.question_id = %s""", q3["id"])[0]
    assert (j["no_response"], j["stt_text"], j["status"], float(j["score"])) == (True, None, "silent", 0.0)
    q4 = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]
    assert (q4["ask_order"], q4["question_type"]) == (4, "main")


def test_identity_mismatch_blocks(client, db_url, monkeypatch):
    """불일치면 바로 '다시 촬영'(남은 횟수)을 알려 주고, 재촬영 3번 뒤에도 같으면 응시를 막고 의심 건 (11/10: 일치해야 통과).
    거리 값은 지원자에게 보이지 않는다"""
    monkeypatch.setattr(media_stub, "face_distance", lambda frame, photo: 0.9)
    app_id = as_candidate(client, 8)
    client.post(f"/api/interview/applications/{app_id}/precheck", json=OK_CHECK)
    done = [client.post(f"/api/interview/applications/{app_id}/identity", files={"frame": ("f.jpg", b"x", "image/jpeg")}).json()
            for _ in range(4)]
    assert done == [{"done": False, "result": "retry", "left": n} for n in (3, 2, 1)] + [{"done": True, "result": "failed"}]
    assert not any("distance" in d or "band" in d for d in done)
    assert client.post(f"/api/interview/applications/{app_id}/identity",
                       files={"frame": ("f.jpg", b"x", "image/jpeg")}).json() == {"done": True, "result": "failed"}   # 다시 해도 결과는 그대로
    s = sql(db_url, "SELECT id, identity_status FROM interview_session WHERE application_id = %s", app_id)[0]
    assert s["identity_status"] == "mismatch"
    assert sql(db_url, "SELECT reason FROM suspicion_case WHERE interview_session_id = %s", s["id"])[0]["reason"] == "identity_mismatch"
    r = client.post(f"/api/interview/applications/{app_id}/prepare")
    assert r.status_code == 409 and "본인 확인이 되지 않아" in r.json()["detail"]               # 일치하지 않으면 넘어가지 않음


def test_precheck_needs_devices_and_consents(client):
    app_id = as_candidate(client, 12)
    p = f"/api/interview/applications/{app_id}/precheck"
    assert client.post(p, json={**OK_CHECK, "consent_overseas": False}).status_code == 400   # 국외 전송은 필수 (1109)
    assert client.post(p, json={**OK_CHECK, "mic": False}).status_code == 400
    assert client.post(f"/api/interview/applications/{app_id}/start").status_code == 409    # 점검 전 시작 없음
    assert client.post(p, json=OK_CHECK).status_code == 200
    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 409  # 본인 확인 전 준비 없음


def test_face_consent_refused_goes_to_human_check(client, db_url):
    """얼굴 생체정보 동의는 별도: 거부해도 응시는 되고, 촬영 없이 '애매' + 담당자 확인 의심 건 (FR-02·03)"""
    app_id = as_candidate(client, 28)
    assert client.post(f"/api/interview/applications/{app_id}/precheck", json={**OK_CHECK, "consent_face": False}).status_code == 200
    with psycopg.connect(db_url) as c:
        st, reason = c.execute("""SELECT s.identity_status, x.reason FROM interview_session s JOIN suspicion_case x ON x.interview_session_id = s.id
                                  WHERE s.application_id = %s""", (app_id,)).fetchone()
    assert (st, reason) == ("unclear", "identity_unclear")
    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 200   # 촬영 없이 다음 단계


def ask(client, sid, text, stayed=30, incident_id=None, history=()):
    msgs = [*history, {"role": "user", "text": text}]
    return client.post(f"/api/interview/sessions/{sid}/inquiry", json={"messages": msgs, "stayed_sec": stayed, "incident_id": incident_id})


def test_inquiry_rule_reply_without_key(client, monkeypatch):
    """키가 없으면 규칙 안내. 시스템 원인이면 머문 시간만큼 추가 시간을 문의 창 하나에 한 번만"""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, sid = begin(client, 9)
    r = ask(client, sid, "화면이 멈췄어요").json()
    assert (r["cause"], r["extra_time_sec"], r["by"]) == ("unknown", 0, "rule") and r["reply"]
    client.post(f"/api/interview/sessions/{sid}/proctor", json={"event_type": "upload_fail", "duration_ms": 0})
    before = client.get(f"/api/interview/sessions/{sid}/state").json()["remaining_sec"]
    r2 = ask(client, sid, "답변이 안 올라가요", incident_id=r["incident_id"]).json()
    assert (r2["incident_id"], r2["cause"], r2["extra_time_sec"]) == (r["incident_id"], "system", 30)
    r3 = ask(client, sid, "아직도요", stayed=60, incident_id=r["incident_id"]).json()
    assert r3["extra_time_sec"] == 30                                               # 같은 창에서 두 번 주지 않음
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert st["phase"] == "think" and st["remaining_sec"] <= before    # 생각 시간은 그대로, 추가 시간은 녹음 시간에 붙는다
    assert client.post(f"/api/interview/sessions/{sid}/inquiry/{r['incident_id']}/stop").json() == {"stopped": True}
    assert client.get(f"/api/interview/sessions/{sid}/state").json()["status"] == "system_error"   # 담당자가 재응시를 줄 수 있음


class _FakeChat:
    def __init__(self, text):
        self.text, self.seen = text, None

    def invoke(self, msgs):
        self.seen = msgs
        return type("R", (), {"content": self.text})()


def test_inquiry_claude_reply_and_guards(client, db_url, monkeypatch):
    """키가 있고 해외 전송에 동의한 응시만 Claude로. 지원자 문장은 연락처를 가리고 태그로 감싸 보낸다. 형식이 틀리면 규칙 안내"""
    from api.interview import chatbot
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    fake = _FakeChat('{"cause": "candidate", "reply": "브라우저 주소창의 마이크 권한을 허용해 주세요."}')
    monkeypatch.setattr(chatbot.llm, "chat_model", lambda *a, **k: fake)
    _, sid = begin(client, 16)
    sql(db_url, "UPDATE interview_session SET overseas_consent = false WHERE id = %s RETURNING id", sid)   # 옛 응시(동의 필수 전) 경우
    assert ask(client, sid, "마이크가 안 돼요").json()["by"] == "rule"
    sql(db_url, "UPDATE interview_session SET overseas_consent = true WHERE id = %s RETURNING id", sid)
    r = ask(client, sid, "마이크가 안 돼요 연락은 010-1234-5678로").json()
    assert (r["cause"], r["by"], r["extra_time_sec"]) == ("candidate", "claude", 0) and "마이크 권한" in r["reply"]
    sent = fake.seen[1][1]
    assert "010-1234-5678" not in sent and "<message from=\"응시자\">" in sent
    assert client.post(f"/api/interview/sessions/{sid}/inquiry/{r['incident_id']}/stop").status_code == 409   # 시스템 원인만 중단
    fake.text = "모르겠습니다"                                                       # JSON이 아니면
    assert ask(client, sid, "다시요").json()["by"] == "rule"


def test_mask_resume_hides_personal_info(db_url):
    snap = sql(db_url, """SELECT a.resume_snapshot FROM application a JOIN candidate c ON c.id = a.candidate_id
                          WHERE c.email = 'cand01@test.local'""")[0]["resume_snapshot"]
    text = store.mask_resume(snap)
    for v in ("김하늘", "010-0000-0001", "cand01@test.local", "상계동", "1997-04-14", "한빛대", "시험용 수준", "성별"):
        assert v not in text, v
    assert "FastAPI" in text and "컴퓨터공학과" in text                # 직무 내용은 남긴다


def test_prepare_twice_at_once_is_ok(client, db_url, monkeypatch):
    """준비 요청이 겹쳐도(두 번 누름·새로고침) 500 없이 1~3번이 한 벌만"""
    app_id = as_candidate(client, 13)
    client.post(f"/api/interview/applications/{app_id}/precheck", json=OK_CHECK)
    client.post(f"/api/interview/applications/{app_id}/identity", files={"frame": ("f.jpg", b"x", "image/jpeg")})
    real = store.add_question

    def racing(db, sid, q, ask_order, *a, **k):     # 첫 질문을 넣기 직전에 다른 요청이 먼저 다 넣은 상황
        if ask_order == 1 and not sql(db_url, "SELECT 1 FROM interview_question WHERE session_id = %s", sid):
            with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as other:
                for i, x in enumerate(routes.engine.prepare(store.context(other, sid)), 1):
                    real(other, sid, x, i)
        return real(db, sid, q, ask_order, *a, **k)
    monkeypatch.setattr(store, "add_question", racing)
    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 200
    sid = sql(db_url, "SELECT id FROM interview_session WHERE application_id = %s", app_id)[0]["id"]
    assert [r["ask_order"] for r in sql(db_url, "SELECT ask_order FROM interview_question WHERE session_id = %s ORDER BY 1", sid)] == [1, 2, 3]


def test_super_admin_reattempt_and_dev_reset(client, db_url, monkeypatch):
    """최고관리자는 끝난 응시(포기·완료)에도 재응시를 줄 수 있고(채용 담당은 장애만), 개발 모드에서는 응시 기록을 초기화할 수 있다"""
    app_id, sid = begin(client, 14)
    p = f"/api/interview/sessions/{sid}/proctor"
    client.post(p, json={"event_type": "tab_leave", "duration_ms": 1000})
    client.post(p, json={"event_type": "tab_leave", "duration_ms": 1000})          # 포기
    as_admin(client, "hr01")                                                        # 채용 담당도 끝난 응시에 줄 수 있다
    assert client.post(f"/api/admin/interviews/{sid}/reattempt").json() == {"next_attempt": 2}
    _, sid2 = begin(client, 14)                                                     # 2차 응시 → 완료로 만든 뒤
    sql(db_url, "UPDATE interview_session SET status = 'completed', end_reason = 'finished', ended_at = now() WHERE id = %s RETURNING id", sid2)
    sql(db_url, "UPDATE application SET status = 'stage2_done' WHERE id = %s RETURNING id", app_id)
    as_admin(client, "admin")
    assert client.post(f"/api/admin/interviews/{sid2}/reattempt").json() == {"next_attempt": 3}
    assert sql(db_url, "SELECT status FROM application WHERE id = %s", app_id)[0]["status"] == "stage2"   # 다시 응시 가능

    monkeypatch.delenv("DEV_QUICK_LOGIN", raising=False)
    assert client.post(f"/api/admin/interviews/{sid2}/reset").status_code == 404     # 개발 모드에서만
    monkeypatch.setenv("DEV_QUICK_LOGIN", "1")
    as_admin(client, "hr01")
    assert client.post(f"/api/admin/interviews/{sid2}/reset").status_code == 403     # 최고관리자만
    as_admin(client, "admin")
    assert client.post(f"/api/admin/interviews/{sid2}/reset").json() == {"reset": True}
    assert sql(db_url, "SELECT count(*) AS n FROM interview_session WHERE application_id = %s", app_id)[0]["n"] == 0
    _, sid3 = begin(client, 14)                                                     # 처음부터 1차로 다시
    assert sql(db_url, "SELECT attempt_no FROM interview_session WHERE id = %s", sid3)[0]["attempt_no"] == 1


def test_dev_unlock_setting(client, db_url, monkeypatch):
    """개발 모드 최고관리자만 설정 잠금을 풀 수 있고, 면접 중인 응시가 있으면 거부"""
    pid = sql(db_url, "SELECT id FROM job_posting")[0]["id"]
    _, sid = begin(client, 15)                                                     # 면접 시작 → 잠김
    url = f"/api/admin/postings/{pid}/interview-setting/unlock"
    monkeypatch.delenv("DEV_QUICK_LOGIN", raising=False)
    as_admin(client, "admin")
    assert client.post(url).status_code == 404                                     # 개발 모드에서만
    monkeypatch.setenv("DEV_QUICK_LOGIN", "1")
    as_admin(client, "hr01")
    assert client.post(url).status_code == 403                                     # 최고관리자만
    as_admin(client, "admin")
    assert client.post(url).status_code == 409                                     # 면접 중인 응시 있음
    sql(db_url, "UPDATE interview_session SET status = 'abandoned', end_reason = 'tab_leave', ended_at = now() WHERE id = %s RETURNING id", sid)
    sql(db_url, """UPDATE interview_session SET status = 'abandoned', end_reason = 'tab_leave', ended_at = now()
                   WHERE status = 'in_progress' RETURNING id""")                   # 다른 시험이 남긴 진행 중 응시도 정리
    assert client.post(url).json()["locked_at"] is None
    cur = client.get(f"/api/admin/postings/{pid}/interview-setting").json()
    body = {k: cur[k] for k in ("company_requirements", "total_questions", "followup_max_depth", "think_sec_non_tech", "think_sec_tech",
                                "answer_max_sec", "silence_skip_sec", "follow_score", "retry_score", "weight_content",
                                "weight_language", "weight_nonverbal", "llm_provider", "llm_eval_model", "llm_fast_model",
                                "llm_local_model")}
    assert client.put(f"/api/admin/postings/{pid}/interview-setting", json={**body, "think_sec_tech": 7}).status_code == 200


def test_nearly_silent_answer_is_no_response(client, db_url):
    """말을 거의 안 한 녹음(침묵 비율 0.9 이상)은 음성 파일이 있어도 무응답 → 기술 질문 0점 (가짜 STT도 실제처럼)"""
    _, sid = begin(client, 17)
    for _ in range(2):
        answer(client, sid, client.get(f"/api/interview/sessions/{sid}/state").json()["question"]["id"])
    q3 = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]
    answer(client, sid, q3["id"], form={**FORM, "silence_ratio": "0.95"})
    j = sql(db_url, """SELECT a.no_response, j.status, j.score FROM interview_answer a JOIN answer_judgement j ON j.answer_id = a.id
                       WHERE a.question_id = %s""", q3["id"])[0]
    assert (j["no_response"], j["status"], float(j["score"])) == (True, "silent", 0.0)


def test_answer_without_voice_is_no_response(client, db_url):
    """말을 안 하고 바로 '답변 끝'을 눌러도(침묵 비율은 낮게 나옴) 소리 난 시간이 거의 없으면 무응답 → 기술 0점"""
    _, sid = begin(client, 18)
    for _ in range(2):
        answer(client, sid, client.get(f"/api/interview/sessions/{sid}/state").json()["question"]["id"])
    q3 = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]
    answer(client, sid, q3["id"], form={**FORM, "silence_ratio": "0", "answer_sec": "2", "voiced_sec": "0.2"})
    j = sql(db_url, """SELECT a.no_response, j.status, j.score FROM interview_answer a JOIN answer_judgement j ON j.answer_id = a.id
                       WHERE a.question_id = %s""", q3["id"])[0]
    assert (j["no_response"], j["status"], float(j["score"])) == (True, "silent", 0.0)
    q4 = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]
    answer(client, sid, q4["id"], form={**FORM, "voiced_sec": "12.5"})                # 말했으면 그대로 판정
    assert sql(db_url, """SELECT a.no_response FROM interview_answer a WHERE a.question_id = %s""", q4["id"])[0]["no_response"] is False
