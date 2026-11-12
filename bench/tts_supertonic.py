"""Supertonic(지금 쓰는 TTS)으로 고정 문장을 읽힌다. tts 컨테이너 안에서 실행 (tasks.ps1 bench-tts).
→ /bench/data/tts_supertonic-3/<목소리>_<id>.wav + timing.csv (합성 초·음성 길이)
STT 시험 음성(정답이 있는 녹음)이자, TTS 비교의 기준 결과가 된다.
"""
import csv
import os
import sys
import time
import wave

sys.path.insert(0, "/bench")
from sentences import SENTENCES, TTS_VOICES  # noqa: E402
from supertonic import TTS  # noqa: E402

MODEL = os.environ.get("TTS_MODEL", "supertonic-3")
OUT = f"/bench/data/tts_{MODEL}"
os.makedirs(OUT, exist_ok=True)

t0 = time.monotonic()
tts = TTS(model=MODEL)
load = time.monotonic() - t0
rows = []
for v in TTS_VOICES:
    style = tts.get_voice_style(v)
    for sid, text, _ in SENTENCES:
        t = time.monotonic()
        wav, _ = tts.synthesize(text, voice_style=style, speed=1.0, lang="ko")
        sec = time.monotonic() - t
        path = f"{OUT}/{v}_{sid}.wav"
        tts.save_audio(wav, path)
        with wave.open(path) as w:
            dur = w.getnframes() / w.getframerate()
        rows.append({"file": os.path.basename(path), "voice": v, "id": sid, "synth_sec": round(sec, 3), "audio_sec": round(dur, 2)})
        print(f"{v} {sid} {sec:.2f}s → {dur:.1f}s", flush=True)
with open(f"{OUT}/timing.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"모델 적재 {load:.1f}s, {len(rows)}개 → {OUT}")
