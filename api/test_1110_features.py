"""11/10 요청: 질문 은행 → 미리 생성·검증 → 출제, 증명사진·면접 중 본인 확인, 표정 기록, 담당자 연락처, 예비 없음"""
import json
import os

from api import pregen
from api.test_interview_flow import FORM, answer, as_candidate, begin, sql

PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) + b"\x00" * 64


def test_question_bank_built_and_verified(db_url):
    rows = sql(db_url, "SELECT job_role, count(*) AS n, sum(verified::int) AS ok FROM question_bank GROUP BY 1")
    by = {r["job_role"]: r for r in rows}
    assert by["백엔드"]["n"] > 0 and by["백엔드"]["ok"] == by["백엔드"]["n"]       # 직무별 회사 질문이 있고 검증 통과


def test_prepare_then_interview_uses_prepared(client, db_url):
    """1차 합격 뒤 미리 만든(검증 통과) 1·2번·기술 본 질문 후보 → 면접 setup·다음 주제가 그것을 출제"""
    app_id = as_candidate(client, 29)
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(db_url, autocommit=True, row_factory=dict_row) as db:
        assert pregen.prepare(db, app_id)["made"] >= 3
        assert pregen.prepare(db, app_id) == {"made": 0}                         # 두 번 해도 한 번만
    rows = sql(db_url, "SELECT slot, status, verify FROM prepared_question WHERE application_id = %s ORDER BY slot", app_id)
    assert [r["slot"] for r in rows][:2] == [1, 2] and all(r["status"] == "ready" and r["verify"]["ok"] for r in rows)
    mains = {r["slot"] for r in rows if r["slot"] >= 4}
    assert mains, "기술 본 질문 후보가 없음"
    _, sid = begin(client, 29)
    qs = sql(db_url, "SELECT ask_order, question_text, defense FROM interview_question WHERE session_id = %s ORDER BY ask_order", sid)
    prep = {r["slot"]: r for r in sql(db_url, "SELECT slot, question_text FROM prepared_question WHERE application_id = %s", app_id)}
    assert qs[0]["question_text"] == prep[1]["question_text"] and qs[1]["question_text"] == prep[2]["question_text"]
    assert (qs[0]["defense"] or {}).get("사전 생성", {}).get("검증") == "통과"
    assert 3 in prep                                                                # 3번(코딩 약점)은 코딩 뒤 → 면접 setup 때 없으면 만듦


def test_verify_catches_bad_questions():
    from contracts import CompanyDoc, Question
    doc = CompanyDoc(chunk_id="PRJ-X-3#s1", doc_type="project", tier=3, topic="X", forbid=["비밀이름"], body="본문")
    ok = Question(kind="tech", tech_stack="X", question_text="결제 승인 지연을 줄이려면 어떻게 설계하시겠어요?", basis="b",
                  source_doc_ids=["PRJ-X-3#s1"], min_tier=3, key_points=["설계"], model="t")
    assert pregen.verify(ok, {doc.chunk_id: doc}, [])["ok"]
    for bad in ("비밀이름 프로젝트를 어떻게 설계하시겠어요?", "PRJ-X-3 문서의 상황을 어떻게 설계하시겠어요?", "연락처 010-1234-5678로 답해 주세요 설계는?"):
        assert not pregen.verify(ok.model_copy(update={"question_text": bad}), {doc.chunk_id: doc}, [])["ok"], bad
    assert not pregen.verify(ok, {doc.chunk_id: doc}, [ok.question_text])["ok"]       # 중복


def test_photo_recheck_and_face_signals(client, db_url):
    app_id = as_candidate(client, 33)
    assert client.post(f"/api/interview/applications/{app_id}/photo", files={"photo": ("p.gif", b"GIF89a", "image/gif")}).status_code == 400
    assert client.post(f"/api/interview/applications/{app_id}/photo", files={"photo": ("p.png", PNG, "image/png")}).json() == {"has_photo": True}
    assert client.get("/api/interview/applications").json()[0]["has_photo"] is True
    key = sql(db_url, "SELECT photo_object_key FROM application WHERE id = %s", app_id)[0]["photo_object_key"]
    assert os.path.exists(os.path.join(os.environ.get("PHOTO_DIR", "/photos"), key))
    _, sid = begin(client, 33)
    assert client.post(f"/api/interview/applications/{app_id}/photo", files={"photo": ("p.png", PNG, "image/png")}).status_code == 409   # 면접 시작 뒤 못 바꿈
    r = client.post(f"/api/interview/sessions/{sid}/identity-recheck", files={"frame": ("f.jpg", b"x", "image/jpeg")})
    assert r.json() == {"recorded": True} and "distance" not in r.text                 # 결과는 지원자에게 안 보임
    assert sql(db_url, "SELECT phase FROM identity_check WHERE session_id = %s ORDER BY id DESC LIMIT 1", sid)[0]["phase"] == "recheck"
    qid = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]["id"]
    sig = [{"t0": 0, "t1": 1500, "label": "미소", "value": {"smile": 0.6}}, {"t0": 1500, "t1": 4000, "label": "긴장", "value": {}},
           {"t0": 0, "t1": 1, "label": "해킹", "value": {}}]
    answer(client, sid, qid, form={**FORM, "face_signals": json.dumps(sig)})
    got = sql(db_url, """SELECT g.label FROM answer_signal g JOIN interview_answer a ON a.id = g.answer_id
                         WHERE a.question_id = %s ORDER BY g.t_start_ms""", qid)
    assert [g["label"] for g in got] == ["미소", "긴장"]                                # 정해진 표정 이름만
    assert "has_score" not in r.text


def test_contact(client):
    c = client.get("/api/site/contact").json()
    assert c["phone"] and c["email"] and "방문" in c["onsite"]


def test_real_face_needs_photo_and_ignores_no_face(client, db_url, monkeypatch):
    """실제 얼굴 대조면 증명사진이 없을 때 본인 확인을 넘어가지 않는다. 얼굴을 못 찾은 촬영은 재촬영 횟수에 안 넣는다 (11/10)"""
    from api import face
    from api.test_interview_flow import OK_CHECK
    app_id = as_candidate(client, 35)
    assert client.post(f"/api/interview/applications/{app_id}/precheck", json=OK_CHECK).status_code == 200
    monkeypatch.setattr(face, "model", lambda: face.REAL)
    g = client.get(f"/api/interview/applications/{app_id}/guide").json()
    assert g["face_real"] is True and g["has_photo"] is False
    frame = {"frame": ("f.jpg", b"x", "image/jpeg")}
    r = client.post(f"/api/interview/applications/{app_id}/identity", files=frame)
    assert r.status_code == 409 and "증명사진" in r.json()["detail"]
    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 409          # 본인 확인 전이라 못 넘어감
    assert client.post(f"/api/interview/applications/{app_id}/photo", files={"photo": ("p.png", PNG, "image/png")}).status_code == 200
    monkeypatch.setattr(face, "distance", lambda *_: None)                                     # 얼굴을 못 찾음
    for _ in range(5):
        assert client.post(f"/api/interview/applications/{app_id}/identity", files=frame).json() == {"done": False, "result": "no_face"}
    monkeypatch.setattr(face, "distance", lambda *_: 0.3)                                      # 일치
    assert client.post(f"/api/interview/applications/{app_id}/identity", files=frame).json() == {"done": True, "result": "match"}
    st = sql(db_url, "SELECT identity_status FROM interview_session WHERE application_id = %s", app_id)[0]["identity_status"]
    assert st == "match"


def test_identity_rechecks_every_shot(client, db_url, monkeypatch):
    """이미 일치한 뒤 다른 사람이 찍으면 그 촬영도 새로 대조해 통과를 거둔다 (저장된 결과를 그대로 돌려주지 않음, 11/10)"""
    from api.interview import media_stub
    from api.test_interview_flow import OK_CHECK
    app_id = as_candidate(client, 36)
    client.post(f"/api/interview/applications/{app_id}/precheck", json=OK_CHECK)
    frame = {"frame": ("f.jpg", b"x", "image/jpeg")}
    monkeypatch.setattr(media_stub, "face_distance", lambda *_: 0.3)
    assert client.post(f"/api/interview/applications/{app_id}/identity", files=frame).json()["result"] == "match"
    monkeypatch.setattr(media_stub, "face_distance", lambda *_: 0.95)                           # 다른 사람
    assert client.post(f"/api/interview/applications/{app_id}/identity", files=frame).json() == {"done": False, "result": "retry", "left": 3}
    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 409             # 통과가 거둬짐
    monkeypatch.setattr(media_stub, "face_distance", lambda *_: 0.25)                           # 본인이 다시
    assert client.post(f"/api/interview/applications/{app_id}/identity", files=frame).json()["result"] == "match"
    assert client.post(f"/api/interview/applications/{app_id}/prepare").status_code == 200
