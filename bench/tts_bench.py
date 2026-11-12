"""TTS 후보로 고정 문장을 읽힌다 (11/12). 후보 이미지 안에서 실행.
  python /bench/tts_bench.py --engine qwen-tts|melo|cosyvoice
→ /bench/data/tts_<이름>/<목소리>_<id>.wav + timing.csv (합성 초·음성 길이). 그다음 stt_bench.py(기준 STT)로 받아 적으면 왕복 CER이 기록된다.
목소리: 내 녹음은 쓰지 않는다 (개인정보). CosyVoice는 목소리 견본이 필요해서 Supertonic이 만든 음성(F1·M1 s01)을 견본으로 쓴다.
"""
import argparse
import csv
import os
import sys
import time

import numpy as np
import soundfile as sf

sys.path.insert(0, "/bench")
from sentences import SENTENCES  # noqa: E402


def qwen_tts():
    import torch
    from qwen_tts import Qwen3TTSModel
    # GTX 1660은 bf16이 없고 fp16은 생성 중 CUDA assert(값 넘침)가 나서 fp32 (11/12)
    m = Qwen3TTSModel.from_pretrained("Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice", device_map="cuda:0", dtype=torch.float32)

    def say(text, voice):
        wavs, sr = m.generate_custom_voice(text=text, language="Korean", speaker=voice)
        return np.asarray(wavs[0]), sr
    return "qwen3-tts-0.6b", ["Sohee"], say


def melo():
    from melo.api import TTS
    m = TTS(language="KR", device="cuda")
    spk = m.hps.data.spk2id["KR"]

    def say(text, voice):
        path = "/tmp/melo.wav"
        m.tts_to_file(text, spk, path, speed=1.0, quiet=True)
        x, sr = sf.read(path)
        return x, sr
    return "melotts-kr", ["KR"], say


def cosyvoice():
    from huggingface_hub import snapshot_download
    from cosyvoice.cli.cosyvoice import AutoModel
    d = snapshot_download("FunAudioLLM/CosyVoice2-0.5B")
    m = AutoModel(model_dir=d)
    ref = next(t for i, t, _ in SENTENCES if i == "s01")
    prompts = {"F1": "/bench/data/tts_supertonic-3/F1_s01.wav", "M1": "/bench/data/tts_supertonic-3/M1_s01.wav"}

    def say(text, voice):
        out = [j["tts_speech"].squeeze(0).cpu().numpy() for j in m.inference_zero_shot(text, ref, prompts[voice], stream=False)]
        return np.concatenate(out), m.sample_rate
    return "cosyvoice2-0.5b", list(prompts), say


ENGINES = {"qwen-tts": qwen_tts, "melo": melo, "cosyvoice": cosyvoice}

ap = argparse.ArgumentParser()
ap.add_argument("--engine", required=True, choices=list(ENGINES))
a = ap.parse_args()
t0 = time.monotonic()
name, voices, say = ENGINES[a.engine]()
print(f"모델 적재 {time.monotonic() - t0:.1f}s", flush=True)
say("준비", voices[0])                                   # 첫 호출 준비(워밍업)는 속도에서 뺀다
out = f"/bench/data/tts_{name}"
os.makedirs(out, exist_ok=True)
rows = []
for v in voices:
    for sid, text, _ in SENTENCES:
        t = time.monotonic()
        x, sr = say(text, v)
        sec = time.monotonic() - t
        sf.write(f"{out}/{v}_{sid}.wav", x, sr)
        rows.append({"file": f"{v}_{sid}.wav", "voice": v, "id": sid, "synth_sec": round(sec, 3), "audio_sec": round(len(x) / sr, 2)})
        print(f"{v} {sid} {sec:.2f}s → {len(x) / sr:.1f}s", flush=True)
with open(f"{out}/timing.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
print(f"{len(rows)}개 → {out}")
