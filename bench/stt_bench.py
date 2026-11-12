"""STT 비교 (11/12). 고정 음성 묶음을 한 모델로 받아 적고 정답과 비교한다. 모델 컨테이너 안에서 실행.
  python /bench/stt_bench.py --engine faster-whisper --model large-v3-turbo [--sets tts_supertonic-3,mine]
결과: /bench/out/stt/<엔진_모델>/<묶음>.csv (파일마다) + /records/speech_bench.csv에 한 줄씩 더함 (포트폴리오 엑셀 'STT·TTS 비교')
TTS 묶음(tts_<모델>)을 기준 STT(large-v3-turbo)로 받아 적으면 그 TTS의 왕복 CER·합성 속도도 한 줄 더한다
지표: CER(글자 오류율, 띄어쓰기·문장부호 뺌) · WER(단어) · 용어 인식률 · 처리 속도(RTF=처리초/음성초) · GPU 메모리 · 무음 환각
엔진을 더할 때는 load_<엔진>()만 하나 더 만든다 (음성 경로 → 글 함수를 돌려줌).
"""
import argparse
import csv
import datetime as dt
import os
import re
import subprocess
import sys
import threading
import time
import wave

import numpy as np

sys.path.insert(0, "/bench")
from sentences import SENTENCES  # noqa: E402

TRUTH = {sid: (text, terms) for sid, text, terms in SENTENCES}
DATA, OUT, REC = "/bench/data", "/bench/out", "/records/speech_bench.csv"
REF_STT = "large-v3-turbo"      # TTS 왕복 CER을 잴 때 쓰는 고정 STT


# ---------- 채점 ----------
def norm(s: str) -> str:
    return re.sub(r"[^\w]", "", s.lower().replace("_", ""))


def lev(a, b) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def score(ref: str, hyp: str, terms: list[list[str]]) -> dict:
    r, h = norm(ref), norm(hyp)
    rw = [norm(w) for w in ref.split() if norm(w)]
    hw = [norm(w) for w in hyp.split() if norm(w)]
    hit = sum(any(norm(v) in h for v in t) for t in terms)
    # 용어를 영어로 적어도 맞게 본다 ("React" = "리액트"): 받아 주는 표기를 정답 표기로 바꾼 뒤 CER
    hn = h
    for t in terms:
        for v in sorted(t[1:], key=len, reverse=True):
            hn = hn.replace(norm(v), norm(t[0]))
    return {"char_err": lev(r, hn), "char_err_raw": lev(r, h), "chars": len(r), "word_err": lev(rw, hw), "words": len(rw), "term_hit": hit, "terms": len(terms)}


# ---------- GPU 메모리 (nvidia-smi 전체 사용량을 0.2초마다 재서 최댓값) ----------
def gpu_used() -> int | None:
    try:
        return int(subprocess.check_output(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True).split()[0])
    except Exception:  # noqa: BLE001  CPU 컨테이너
        return None


class Peak(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.peak, self.stop = gpu_used() or 0, False

    def run(self):
        while not self.stop:
            self.peak = max(self.peak, gpu_used() or 0)
            time.sleep(0.2)


# ---------- 엔진 ----------
def load_faster_whisper(model: str, device: str):
    from faster_whisper import WhisperModel
    compute = "int8_float16" if device == "cuda" else "int8"
    m = WhisperModel(model, device=device, compute_type=compute)

    def run(path: str) -> str:          # 서비스(stt/app.py)와 같은 설정
        segs, _ = m.transcribe(path, language="ko", beam_size=5, vad_filter=True, condition_on_previous_text=False)
        segs = [s for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        return " ".join(s.text.strip() for s in segs).strip()
    return run, f"{compute}"


# 지금 모델 보완 시험 (11/12): 회사·기술 용어 힌트 + 자막류 환각 문구 거르기. 힌트는 시험 문장에 맞춘 게 아니라
# 회사 이름 + 백엔드 면접에 흔한 용어 묶음 (시험 용어보다 넓게)
HINT_WORDS = ("새벽소프트 API REST JWT OAuth Redis Kafka RabbitMQ Celery Docker Kubernetes 파드 GitHub Actions CI/CD Elasticsearch "
              "Slack PostgreSQL MySQL 인덱스 트랜잭션 Read Committed 낙관적 락 캐시 p95 p99 N+1 조인 React useMemo TypeScript "
              "Spring FastAPI Django BM25 RRF 리랭커 벡터 검색 LLM RAG 마이크로서비스 웹훅 HttpOnly 쿠키")
JUNK = re.compile(r"자막|시청해 ?주셔서|구독|좋아요|아멘|MBC|KBS|SBS")


def load_faster_whisper_hint(model: str, device: str):
    from faster_whisper import WhisperModel
    compute = "int8_float16" if device == "cuda" else "int8"
    m = WhisperModel(model, device=device, compute_type=compute)

    def run(path: str) -> str:
        segs, _ = m.transcribe(path, language="ko", beam_size=5, vad_filter=True, condition_on_previous_text=False, hotwords=HINT_WORDS)
        segs = [s for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -1.0)]
        text = " ".join(s.text.strip() for s in segs).strip()
        return JUNK.split(text)[0].strip() if JUNK.search(text) else text    # 자막류 문구부터 뒤는 버림
    return run, f"{compute} + 용어 힌트·환각 거르기"


def _audio16k(path: str):
    import librosa
    return librosa.load(path, sr=16000, mono=True)[0]


def load_hf_whisper(model: str, device: str):
    """transformers Whisper (한국어 추가 학습판 등). GTX 1660은 bf16이 없어 fp16. 시험 음성은 모두 30초 안이라 한 번에"""
    import torch
    from transformers import GenerationConfig, WhisperForConditionalGeneration, WhisperProcessor
    proc = WhisperProcessor.from_pretrained(model)
    m = WhisperForConditionalGeneration.from_pretrained(model, torch_dtype=torch.float16).to(device)
    if "korean" in model:            # 추가 학습판은 생성 설정이 옛 형식이라 language 인자를 못 받는다 → 원래 모델(turbo)의 생성 설정을 쓴다
        m.generation_config = GenerationConfig.from_pretrained("openai/whisper-large-v3-turbo")

    def run(path: str) -> str:
        feats = proc(_audio16k(path), sampling_rate=16000, return_tensors="pt").input_features.to(device, torch.float16)
        with torch.no_grad():
            ids = m.generate(feats, language="ko", task="transcribe")
        return proc.batch_decode(ids, skip_special_tokens=True)[0].strip()
    return run, "fp16"


def load_moonshine(model: str, device: str):
    """Moonshine (한국어 전용 소형). 반복 환각을 막으려고 생성 길이를 음성 길이에 비례해 막는다.
    모델 카드의 1초당 6.5토큰은 영어 기준이라 한국어는 문장이 잘림(11/12 첫 측정 CER 49%) → 1초당 15토큰"""
    import torch
    from transformers import AutoProcessor, MoonshineForConditionalGeneration
    proc = AutoProcessor.from_pretrained(model)
    m = MoonshineForConditionalGeneration.from_pretrained(model).to(device)

    def run(path: str) -> str:
        x = _audio16k(path)
        inp = proc(x, sampling_rate=16000, return_tensors="pt").to(device)
        with torch.no_grad():
            ids = m.generate(**inp, max_length=max(10, int(len(x) / 16000 * 15)))
        return proc.decode(ids[0], skip_special_tokens=True).strip()
    return run, "fp32"


def load_qwen_asr(model: str, device: str):
    import torch
    from qwen_asr import Qwen3ASRModel
    m = Qwen3ASRModel.from_pretrained(model, dtype=torch.float16, device_map=f"{device}:0" if device == "cuda" else device,
                                      max_inference_batch_size=1, max_new_tokens=512)

    def run(path: str) -> str:
        return (m.transcribe(audio=path, language="Korean")[0].text or "").strip()
    return run, "fp16"


def load_sensevoice(model: str, device: str):
    from funasr import AutoModel
    from funasr.utils.postprocess_utils import rich_transcription_postprocess
    m = AutoModel(model=model, vad_model="fsmn-vad", device=f"{device}:0" if device == "cuda" else device, hub="hf", disable_update=True)

    def run(path: str) -> str:
        r = m.generate(input=path, language="ko", use_itn=True)
        return rich_transcription_postprocess(r[0]["text"]).strip() if r else ""
    return run, "fp32"


ENGINES = {"faster-whisper": load_faster_whisper, "faster-whisper-hint": load_faster_whisper_hint, "hf-whisper": load_hf_whisper, "moonshine": load_moonshine,
           "qwen-asr": load_qwen_asr, "sensevoice": load_sensevoice}


# ---------- 무음·잡음 음성 (환각 시험) ----------
def make_silence():
    d = f"{DATA}/silence"
    os.makedirs(d, exist_ok=True)
    rng = np.random.default_rng(0)
    clips = {"zero10": np.zeros(160000), "hiss10": rng.normal(0, 0.003, 160000), "fan10": np.convolve(rng.normal(0, 0.02, 160000), np.ones(50) / 50, "same")}
    for name, x in clips.items():
        p = f"{d}/{name}.wav"
        if not os.path.exists(p):
            with wave.open(p, "wb") as w:
                w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
                w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return sorted(os.listdir(d))


def dur(path: str) -> float:
    try:
        with wave.open(path) as w:
            return w.getnframes() / w.getframerate()
    except Exception:  # noqa: BLE001  wav가 아니면 av로
        import av
        with av.open(path) as c:
            return float(c.duration or 0) / 1e6


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", required=True, choices=list(ENGINES))
    ap.add_argument("--model", required=True)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--sets", default="")
    ap.add_argument("--note", default="")
    ap.add_argument("--skip-silence", action="store_true")      # TTS 왕복처럼 무음 시험이 필요 없을 때
    a = ap.parse_args()
    sets = [s for s in a.sets.split(",") if s] or sorted(d for d in os.listdir(DATA) if os.path.isdir(f"{DATA}/{d}") and d != "silence")
    name = f"{a.engine}_{a.model}".replace("/", "-")
    os.makedirs(f"{OUT}/stt/{name}", exist_ok=True)

    base = gpu_used()
    peak = Peak()
    peak.start()
    t = time.monotonic()
    run, detail = ENGINES[a.engine](a.model, a.device)
    load_sec = time.monotonic() - t
    run(f"{DATA}/silence/{make_silence()[0]}")          # 첫 호출 준비(워밍업)는 속도에서 뺀다

    summary = []
    for s in sets + ([] if a.skip_silence else ["silence"]):
        files = sorted(f for f in os.listdir(f"{DATA}/{s}") if f.endswith((".wav", ".webm")))
        if not files:                                   # 아직 녹음 안 한 묶음
            continue
        rows = []
        for f in files:
            p = f"{DATA}/{s}/{f}"
            t = time.monotonic()
            hyp = run(p)
            sec = time.monotonic() - t
            row = {"file": f, "sec": round(sec, 3), "audio_sec": round(dur(p), 2), "hyp": hyp}
            sid = re.search(r"([slt]\d\d)", f)
            if s != "silence" and sid and sid.group(1) in TRUTH:
                ref, terms = TRUTH[sid.group(1)]
                row.update(ref=ref, **score(ref, hyp, terms))
            rows.append(row)
            print(f"[{s}] {f} {sec:.2f}s | {hyp[:60]}", flush=True)
        with open(f"{OUT}/stt/{name}/{s}.csv", "w", newline="", encoding="utf-8-sig") as fp:
            keys = list(dict.fromkeys(k for r in rows for k in r))
            w = csv.DictWriter(fp, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
        sec, asec = sum(r["sec"] for r in rows), sum(r["audio_sec"] for r in rows)
        sc = [r for r in rows if "chars" in r]
        summary.append({
            "date": dt.date.today().isoformat(), "kind": "stt", "model": f"{a.engine} {a.model}", "detail": f"{a.device} {detail}", "set": s, "n": len(rows),
            "cer": round(sum(r["char_err"] for r in sc) / max(1, sum(r["chars"] for r in sc)), 4) if sc else "",
            "cer_raw": round(sum(r["char_err_raw"] for r in sc) / max(1, sum(r["chars"] for r in sc)), 4) if sc else "",
            "wer": round(sum(r["word_err"] for r in sc) / max(1, sum(r["words"] for r in sc)), 4) if sc else "",
            "term_rate": round(sum(r["term_hit"] for r in sc) / max(1, sum(r["terms"] for r in sc)), 3) if sc else "",
            "rtf": round(sec / max(asec, 0.01), 3), "avg_sec": round(sec / max(1, len(rows)), 2),
            "hallucinated": sum(bool(r["hyp"]) for r in rows) if s == "silence" else "",
            "load_sec": round(load_sec, 1), "gpu_mb": (peak.peak - base) if base is not None else "", "note": a.note,
        })
        if s.startswith("tts_") and a.engine == "faster-whisper" and a.model == REF_STT and os.path.exists(f"{DATA}/{s}/timing.csv"):
            tm = list(csv.DictReader(open(f"{DATA}/{s}/timing.csv", encoding="utf-8")))
            syn, au = sum(float(r["synth_sec"]) for r in tm), sum(float(r["audio_sec"]) for r in tm)
            summary.append({**summary[-1], "kind": "tts", "model": s[4:], "detail": f"왕복: {a.engine} {a.model}", "set": "고정 문장",
                            "rtf": round(syn / au, 3), "avg_sec": round(syn / len(tm), 2), "load_sec": "", "gpu_mb": ""})
    peak.stop = True
    new = not os.path.exists(REC)
    with open(REC, "a", newline="", encoding="utf-8") as fp:
        w = csv.DictWriter(fp, fieldnames=list(summary[0]))
        if new:
            w.writeheader()
        w.writerows(summary)
    for r in summary:
        print(r)


if __name__ == "__main__":
    main()
