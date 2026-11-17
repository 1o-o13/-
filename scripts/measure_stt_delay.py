"""STT 표시 지연 측정 (11/17): 답변 끝 → 인식 글이 화면에 뜨기까지 몇 초인지, 답변 길이별로 잰다.
  docker compose exec -T api python scripts/measure_stt_delay.py

- 화면에 뜨는 시각 = (음성 업로드) + STT 대기열·인식(stt 컨테이너, faster-whisper large-v3-turbo) + DB 기록 + SSE 확인(1초 간격)
- 여기서는 실제 면접과 같은 대기열('stt' 큐, stt.transcribe 작업)에 음성을 넣고 결과가 올 때까지를 잰다.
  음성은 김하늘 재응시 답변 인식 글을 TTS(Supertonic)로 읽은 것 (지원자 실제 목소리 아님). 길이: 30·60·120·180초(답변 최대) 각 3번
- 측정용 음성은 끝나면 지운다. 결과는 records/measurements.csv에 덧붙인다
"""
import csv
import datetime as dt
import os
import statistics
import sys
import time
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from api.db import connect  # noqa: E402
from api.interview import voice  # noqa: E402
from worker.app import celery  # noqa: E402

TARGETS = [30, 60, 120, 180]
REPEAT = 3
AUDIO = os.environ.get("AUDIO_DIR", "/audio")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "records", "measurements.csv")


def sentences() -> list[str]:
    with connect() as db:
        rows = db.execute("""SELECT a.stt_original FROM interview_answer a JOIN interview_question q ON q.id = a.question_id
                             WHERE q.session_id = (SELECT max(session_id) FROM interview_question q2 JOIN interview_answer a2 ON a2.question_id = q2.id
                                                   WHERE a2.stt_model LIKE 'faster-whisper%%')
                               AND a.stt_original IS NOT NULL ORDER BY q.ask_order""").fetchall()
    out = []
    for r in rows:
        out += [s.strip() + "." for s in r["stt_original"].replace("?", ".").split(".") if len(s.strip()) > 5]
    return out


def build(sec: int, pool: list[str], start: int) -> tuple[str, float]:
    """문장별 TTS 음성을 이어 붙여 sec초 근처 길이의 wav를 만든다"""
    frames, params, total, i = [], None, 0.0, start
    while total < sec:
        p = voice.make(-(2_000_000 + i), pool[i % len(pool)])
        i += 1
        if not p:
            continue
        with wave.open(p) as w:
            params = params or w.getparams()
            frames.append(w.readframes(w.getnframes()))
            total += w.getnframes() / w.getframerate()
    key = f"stt_delay_{sec}_{start}.wav"
    with wave.open(os.path.join(AUDIO, key), "wb") as w:
        w.setparams(params)
        w.writeframes(b"".join(frames))
    return key, round(total, 1)


def main() -> None:
    pool = sentences()
    print("문장", len(pool), flush=True)
    res = {s: [] for s in TARGETS}
    celery.send_task("stt.transcribe", args=["__warm__.wav", ""], queue="stt")   # 첫 호출 준비 (실패해도 됨)
    n = 0
    for rep in range(REPEAT):
        for sec in TARGETS:
            key, length = build(sec, pool, n * 7)
            n += 1
            t = time.monotonic()
            r = celery.send_task("stt.transcribe", args=[key, ""], queue="stt").get(timeout=300)
            took = time.monotonic() - t
            path = os.path.join(AUDIO, key)
            if os.path.exists(path):
                os.remove(path)
            ok = "error" not in r
            res[sec].append((length, took, ok))
            print(f"{rep + 1}회 {sec:>3}초 목표 · 음성 {length}초 · 인식 {took:.1f}초 · {'성공' if ok else r.get('error')}", flush=True)
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for sec, xs in res.items():
        took = [x[1] for x in xs if x[2]]
        if not took:
            continue
        avg_len = statistics.mean(x[0] for x in xs)
        shown = statistics.mean(took) + 0.5      # + SSE 확인 평균 0.5초(1초 간격)
        rows.append([now, "STT 표시 지연", f"답변 {sec}초 (음성 평균 {avg_len:.0f}초)",
                     f"인식 평균 {statistics.mean(took):.1f}초 (최대 {max(took):.1f}초) → 화면 약 {shown:.1f}초",
                     f"{len(took)}/{len(xs)}회 성공, large-v3-turbo GPU, 동시 1명, TTS 음성, 업로드 시간 제외"])
    with open(OUT, "a", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(rows)
    for r in rows:
        print(" | ".join(r[2:]))


if __name__ == "__main__":
    main()
