"""답변 인식 글 지원자 확인·수정 (11/11): 답변 → 인식 글 보여 주기 → 30% 넘게 고치면 거부 → 오류만 고쳐 '완료' → 판정·다음 질문.
원본·수정본·바뀐 비율은 관리자 리포트에. 확인 시간이 지나면 원본 그대로 진행"""
from api.test_interview_flow import FORM, answer, as_admin, begin

from worker import tasks


def test_review_edit_limit_then_next_question(client, monkeypatch):
    held = []
    monkeypatch.setattr(tasks.stt_review_timeout, "apply_async", lambda args, countdown: held.append((args, countdown)))  # 시간 초과는 따로 확인
    _, sid = begin(client, 23)
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    q1 = st["question"]
    r = answer(client, sid, q1["id"])
    assert r.status_code == 202 and "answer_id" in r.json()
    aid = r.json()["answer_id"]
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert st["phase"] == "review" and st["question"] is None                         # 다음 질문은 확인 뒤에
    rv = st["review"]
    assert rv["answer_id"] == aid and rv["ready"] and rv["text"] and 55 < rv["remaining_sec"] <= 60
    assert held == [((aid,), 65)]                                                      # 60초 + 여유 5초 뒤 원본으로 진행
    url = f"/api/interview/sessions/{sid}/answers/{aid}/confirm"
    r = client.post(url, json={"text": "말하지 않은 완전히 새로운 모범 답안을 길게 써 넣습니다. 인덱스와 캐시와 큐를 모두 설계했습니다."})
    assert r.status_code == 422 and "틀린 부분만" in r.json()["detail"]               # 30% 넘게 바꾸면 거부
    fixed = rv["text"][:-3] + "입니다."                                                 # 끝 몇 글자만 고침 (인식 오류 수정)
    r = client.post(url, json={"text": fixed})
    assert r.status_code == 200 and r.json() == {"confirmed": True, "edited": True}
    assert client.post(url, json={"text": None}).status_code == 409                    # 한 번만
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert st["phase"] == "think" and st["question"]["ask_order"] == 2                 # 완료 → 판정 → 다음 질문

    q2 = st["question"]                                                                # 그대로 '완료'
    aid2 = answer(client, sid, q2["id"]).json()["answer_id"]
    assert client.post(f"/api/interview/sessions/{sid}/answers/{aid2}/confirm", json={}).json() == {"confirmed": True, "edited": False}

    q3 = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]       # 확인하지 않고 시간이 지남 → 원본으로 진행
    aid3 = answer(client, sid, q3["id"]).json()["answer_id"]
    tasks.stt_review_timeout(aid3)
    assert client.get(f"/api/interview/sessions/{sid}/state").json()["question"]["ask_order"] == 4
    assert client.post(f"/api/interview/sessions/{sid}/answers/{aid3}/confirm", json={}).status_code == 409

    silent = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]    # 무응답은 확인할 글이 없어 바로 다음
    answer(client, sid, silent["id"], form={**FORM, "voiced_sec": "0.1"})
    assert client.get(f"/api/interview/sessions/{sid}/state").json()["phase"] == "think"

    as_admin(client, "hr01")                                                           # 리포트: 원본·수정본·바뀐 비율
    qs = {q["ask_order"]: q for q in client.get(f"/api/admin/interviews/{sid}").json()["questions"]}
    assert qs[1]["stt_text"] == fixed and qs[1]["stt_original"] == rv["text"] and 0 < float(qs[1]["stt_edit_ratio"]) <= 0.3
    assert float(qs[2]["stt_edit_ratio"]) == 0 and qs[3]["stt_edit_ratio"] is None and qs[3]["stt_text"] == qs[3]["stt_original"]
