"""실제 음성 모드(STT_MODE=real·TTS_MODE=real)의 연결 시험. stt·tts 컨테이너 대신 큐 전송·HTTP를 바꿔 끼워 흐름만 본다."""
import os

import pytest

from api.interview import voice
from api.test_interview_flow import FORM, answer, begin, sql
from worker import tasks


@pytest.fixture
def real(monkeypatch):
    monkeypatch.setenv("STT_MODE", "real")
    sent = []
    monkeypatch.setattr(tasks.celery, "send_task", lambda name, args, queue, link: sent.append((name, args, queue, link)))
    return sent


def test_answer_goes_to_stt_queue_then_continues(client, db_url, real):
    app_id, sid = begin(client, 24)
    q = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]
    assert answer(client, sid, q["id"], form={**FORM, "voiced_sec": "12.0"}).status_code == 202
    (name, args, queue, link), = real                                   # 글로 바꾸는 일은 stt 컨테이너 큐로
    assert (name, queue) == ("stt.transcribe", "stt") and link.task == tasks.after_stt.name
    key = args[0]
    assert os.path.exists(os.path.join(os.environ["AUDIO_DIR"], key))   # STT 전에는 음성이 남아 있음
    tasks.after_stt({"text": "인턴 때 경로 계산 지연을 측정으로 찾았습니다", "sec": 1.2, "model": "faster-whisper large-v3-turbo"},
                    *link.args)
    assert not os.path.exists(os.path.join(os.environ["AUDIO_DIR"], key))   # STT 뒤 바로 지움
    a = sql(db_url, "SELECT stt_text, stt_model, no_response, audio_object_key FROM interview_answer WHERE question_id = %s", q["id"])[0]
    assert a == {"stt_text": "인턴 때 경로 계산 지연을 측정으로 찾았습니다", "stt_model": "faster-whisper large-v3-turbo",
                 "no_response": False, "audio_object_key": None}
    assert client.get(f"/api/interview/sessions/{sid}/state").json()["question"]["ask_order"] == 2   # 판정 뒤 다음 질문


def test_silence_skips_stt(client, db_url, real):
    app_id, sid = begin(client, 25)
    q = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]
    answer(client, sid, q["id"], form={**FORM, "voiced_sec": "0.1"})          # 거의 말 안 함 → 빈 음성
    assert real == []                                                          # Whisper에 보내지 않음 (침묵에서 문장을 지어내지 않게)
    a = sql(db_url, "SELECT no_response, stt_model FROM interview_answer WHERE question_id = %s", q["id"])[0]
    assert a == {"no_response": True, "stt_model": "silence"}


def test_stt_error_goes_on_with_no_stt(client, db_url, real):
    """STT 실패 → 음성은 지우고 면접은 계속: 이 문항은 no_stt로 기록하고 다음 문항 (활동다이어그램 1109)"""
    app_id, sid = begin(client, 26)
    q = client.get(f"/api/interview/sessions/{sid}/state").json()["question"]
    answer(client, sid, q["id"], form={**FORM, "voiced_sec": "8"})
    tasks.after_stt({"error": "RuntimeError: CUDA failed", "model": "x"}, *real[0][3].args)
    st = client.get(f"/api/interview/sessions/{sid}/state").json()
    assert st["status"] == "in_progress" and st["question"]["ask_order"] == 2
    assert sql(db_url, """SELECT j.status FROM answer_judgement j JOIN interview_answer a ON a.id = j.answer_id
                          WHERE a.question_id = %s""", q["id"])[0]["status"] == "no_stt"
    assert not os.listdir(os.environ["AUDIO_DIR"]) or all(not f.endswith(".webm") for f in os.listdir(os.environ["AUDIO_DIR"]))


def test_question_audio_only_for_asked_questions(client, db_url, monkeypatch):
    monkeypatch.setenv("TTS_MODE", "real")
    made = []

    def fake_make(qid, text):
        made.append(qid)
        p = os.path.join(os.environ["AUDIO_DIR"], f"t{qid}.wav")
        open(p, "wb").write(b"RIFF....WAVE")
        return p
    monkeypatch.setattr(voice, "make", fake_make)
    app_id, sid = begin(client, 27)
    qs = sql(db_url, "SELECT id, asked_at FROM interview_question WHERE session_id = %s ORDER BY ask_order", sid)
    r = client.get(f"/api/interview/sessions/{sid}/questions/{qs[0]['id']}/audio")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
    assert client.get(f"/api/interview/sessions/{sid}/questions/{qs[1]['id']}/audio").status_code == 404   # 아직 안 물어본 2번
    from collections import Counter                                            # 준비 때 1~3번을 미리 만들고, 화면 요청은 1번만 통과
    assert Counter(made) == Counter([q["id"] for q in qs[:3]] + [qs[0]["id"]])
