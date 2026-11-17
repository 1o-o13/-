"""시연용: 김하늘(지원 1번) 면접을 실제 흐름 그대로 처음부터 다시 본다 (11/16, 11/17 다시 만듦). E2E 뒤에 실행한다.
  docker compose exec -T api python scripts/demo_reinterview.py

E2E는 가짜 마이크라 3번 이후 답변이 비어 과락으로 끝난다. 시연 화면에 '면접을 잘 본 합격자'가 필요해서, 점수를 손으로 넣지 않고
실제 면접을 한 번 더 돌린다: 사전 점검 → 본인 확인 → 질문 준비 → 10문항 (꼬리질문·재질문은 판정 점수에 따라 그래프가 정함) → 최종 평가.
- 답변 글: 예시 답변 프롬프트(api/prompts/sample_answer.md)를 LLM 관문으로 부름 (tier 1·2 근거면 사내 모델)
- 답변 음성: 그 글을 TTS(Supertonic)로 읽은 음성 → 실제 STT → 인식 글 확인(틀린 곳만 원래 글로 고침, 30% 안) → 판정
- 본인 확인: ※ 시연 데이터. 증명사진을 두지 않으므로(11/17 실제 인물 사진 삭제) 대조 없이 '일치' 기록만 DB에 남긴다.
  라이브니스도 화면 동작이라 통과로 기록
- 끝나면 hr01이 확정 → 2차 종합 점수, 최종 결과는 합격 (이미 발표된 공고라 화면 버튼 대신 DB에 결정·단계 기록)
"""
import os
import sys
import time
import wave

import httpx
from pydantic import BaseModel

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api import face, llm_gate, stage  # noqa: E402
from api.admin.routes import rank_stage2  # noqa: E402
from api.db import connect  # noqa: E402
from api.interview import store, voice  # noqa: E402

APP = 1
API = "http://localhost:8000/api"
WHY = "시연 데이터: 실제 흐름으로 면접 다시 진행 (scripts/demo_reinterview.py)"


class SampleOut(BaseModel):
    answer: str


def reset() -> None:
    """이전 응시·2차 점수·최종 결정을 지우고 2차 대상으로 되돌린다"""
    with connect() as db, db.transaction():
        db.execute("DELETE FROM stage_result WHERE application_id = %s AND stage = 'final'", (APP,))
        stage.move(db, APP, "interview", "admin", None, WHY)
        db.execute("""DELETE FROM ai_error_alert WHERE interview_evaluation_id IN (SELECT e.id FROM interview_evaluation e
                      JOIN interview_session s ON s.id = e.session_id WHERE s.application_id = %s)""", (APP,))
        db.execute("DELETE FROM suspicion_case WHERE application_id = %s AND stage = 'interview'", (APP,))
        db.execute("DELETE FROM interview_session WHERE application_id = %s", (APP,))
        db.execute("DELETE FROM stage2_score WHERE application_id = %s", (APP,))
        db.execute("UPDATE application SET status = 'stage2' WHERE id = %s", (APP,))
        rank_stage2(db, db.execute("SELECT posting_id FROM application WHERE id = %s", (APP,)).fetchone()["posting_id"])


STRONG = ("이번에는 아주 잘 준비한 지원자의 답변으로 쓰세요. 위의 200~350자 대신 90~120초 분량(600~800자)으로, 아래 핵심 요소를 하나도 빠짐없이 "
          "정확히 다루고, 참고 회사 상황에 어떻게 적용할지, 도구·수치·트레이드오프·검증 방법까지 구체적으로 말합니다. "
          "이력서 경험을 근거로 들되 지어낸 회사 이름은 쓰지 않습니다.\n[핵심 요소]\n")


def strong_answer(sid: int, qid: int) -> str:
    """예시 답변을 '잘 준비한 지원자' 길이·깊이로. LLM 관문을 거친다 (tier 1·2 근거면 사내 모델). 짧게 나오면 한 번 더"""
    with connect() as db:
        q = store.to_question(db.execute("SELECT * FROM interview_question WHERE id = %s", (qid,)).fetchone())
        ctx = store.context(db, sid)
    docs = [d.body[:800] for d in ctx.docs if d.chunk_id in q.source_doc_ids]
    best = ""
    for _ in range(3):
        out = llm_gate.call("sample_answer", SampleOut, "sample_answer",
                            {"question": q.question_text, "evidence": "\n".join(docs) or "(없음)", "resume": ctx.resume_text[:2000] or "(없음)"},
                            llm_cfg=ctx.llm, min_tier=q.min_tier, consent=ctx.overseas_consent, session_id=sid,
                            application_id=ctx.application_id, extra=STRONG + ", ".join(q.key_points), max_tokens=3000).out
        if out and len(out.answer) > len(best):
            best = out.answer
        if len(best) >= 400:                      # 11/16: 꼬리질문에 141자짜리 답이 나와 0점이 된 적이 있어 길이를 확인
            break
    if not best:
        raise SystemExit("예시 답변을 만들지 못했습니다")
    return best[:900]


def ok(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        raise SystemExit(f"{r.request.method} {r.request.url.path} → {r.status_code} {r.text[:300]}")
    return r.json()


def wait(c: httpx.Client, sid: int, until, sec: int = 240) -> dict:
    t = time.monotonic()
    while time.monotonic() - t < sec:
        st = ok(c.get(f"{API}/interview/sessions/{sid}/state"))
        if until(st):
            return st
        time.sleep(1)
    raise SystemExit(f"기다리다 시간 초과: {st['phase']}")


def main() -> None:
    reset()
    c = httpx.Client(timeout=180)
    ok(c.post(f"{API}/auth/dev/login/cand1"))
    ok(c.post(f"{API}/interview/applications/{APP}/precheck",
              json={"chrome": True, "camera": True, "mic": True, "single_face": True, "upload_mbps": 20.0,
                    "consent_voice": True, "consent_ai": True, "consent_overseas": True, "consent_face": True}))
    with connect() as db, db.transaction():      # ※ 시연 데이터: 얼굴 대조 없이 '일치' 기록 (증명사진을 두지 않음)
        s = db.execute("SELECT id FROM interview_session WHERE application_id = %s ORDER BY id DESC LIMIT 1", (APP,)).fetchone()["id"]
        db.execute("INSERT INTO identity_check(session_id, phase, retake_no, distance, band, model) VALUES (%s, 'start', 0, 0, 'match', %s)",
                   (s, face.model()))
        db.execute("UPDATE interview_session SET identity_status = 'match' WHERE id = %s", (s,))
    print("본인 확인: 시연 기록(일치)", flush=True)
    ok(c.post(f"{API}/interview/applications/{APP}/liveness", json={"passed": True}))
    sid = ok(c.post(f"{API}/interview/applications/{APP}/prepare"))["session_id"]
    t = time.monotonic()
    while True:
        r = c.post(f"{API}/interview/applications/{APP}/start")
        if r.status_code < 400:
            break
        if time.monotonic() - t > 300:
            ok(r)
        time.sleep(2)
    print("시작 sid", sid, flush=True)
    while True:
        st = wait(c, sid, lambda s: s["status"] != "in_progress" or s["phase"] in ("think", "record"))
        if st["status"] != "in_progress":
            break
        q = st["question"]
        text = strong_answer(sid, q["id"])
        wav = voice.make(-(1_000_000 + q["id"]), text)
        with wave.open(wav) as w:
            sec = round(w.getnframes() / w.getframerate(), 1)
        with open(wav, "rb") as f:
            a = ok(c.post(f"{API}/interview/sessions/{sid}/questions/{q['id']}/answer",
                          files={"audio": ("answer.webm", f.read(), "audio/wav")},
                          data={"answer_sec": sec, "silence_ratio": 0.06, "finished_in_time": "true", "voiced_sec": sec}))
        os.remove(wav)                               # 시연용 답변 음성은 남기지 않는다
        rv = wait(c, sid, lambda s: s["status"] != "in_progress" or (s["review"] or {}).get("ready"))["review"]
        if rv:
            fix = text if store.edit_ratio(rv["text"], text) <= store.EDIT_MAX else None   # 인식이 틀린 곳만 원래 말한 글로
            ok(c.post(f"{API}/interview/sessions/{sid}/answers/{a['answer_id']}/confirm", json={"text": fix}))
        wait(c, sid, lambda s: s["status"] != "in_progress" or (s["question"] and s["question"]["id"] != q["id"]) or s["phase"] == "ended")
        print(f"{q['ask_order']:>2}번 {q['kind']:<8} {q['question_type']:<9} 깊이 {q['depth']} · 답변 {sec}초 · {len(text)}자", flush=True)
    t = time.monotonic()
    while True:
        with connect() as db:
            ev = db.execute("""SELECT id, total_score, status FROM interview_evaluation WHERE session_id = %s
                               ORDER BY version_no DESC LIMIT 1""", (sid,)).fetchone()
        if (ev and ev["status"] != "checking") or time.monotonic() - t > 600:
            break
        time.sleep(3)
    print("최종 평가", ev and dict(ev), flush=True)
    a = httpx.Client(timeout=120)
    ok(a.post(f"{API}/auth/dev/login/hr01"))
    print("확정", ok(a.post(f"{API}/admin/interviews/{sid}/confirm"))["stage2_score"], flush=True)
    with connect() as db, db.transaction():
        hr = db.execute("SELECT id FROM admin_user WHERE login_id = 'hr01'").fetchone()["id"]
        db.execute("""INSERT INTO stage_result(application_id, stage, result, decided_by) VALUES (%s, 'final', 'pass', %s)
                      ON CONFLICT (application_id, stage) DO UPDATE SET result = 'pass', decided_by = EXCLUDED.decided_by, decided_at = now()""",
                   (APP, hr))
        db.execute("UPDATE application SET status = 'final_passed' WHERE id = %s", (APP,))
        stage.move(db, APP, "final_pass", "admin", hr, WHY, strict=True)
        s = db.execute("""SELECT s.interview_score, s.coding_score, s.total_score, s.ai_rank, s.ai_recommendation FROM stage2_score s
                          WHERE application_id = %s""", (APP,)).fetchone()
    print("2차 종합", dict(s), "→ 최종 합격")


if __name__ == "__main__":
    main()
