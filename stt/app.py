"""STT 작업자 (faster-whisper large-v3-turbo, GPU). Redis 큐 'stt'에서 작업을 받아 답변 음성을 한국어 글로 바꾼다.

- 음성 파일은 api·worker와 같은 볼륨(/audio)에서 읽기만 한다. 지우는 건 worker (STT 직후, 개인정보 규칙)
- 결과는 link로 이어진 worker 작업(worker.tasks.after_stt)에 넘긴다 → DB는 worker만 다룬다
- 침묵·잡음에서 지어내는 문장(환각)을 줄이려고 VAD를 켜고, 말이 아닐 확률이 높은 구간은 버린다
"""
import dataclasses
import os
import re
import time

import numpy as np

from celery import Celery

MODEL = os.environ.get("STT_WHISPER_MODEL", "large-v3-turbo")
DEVICE = os.environ.get("STT_DEVICE", "cuda")
# GTX 1660 SUPER에서 112초 답변: float16 30.7초, int8_float16 9.4초 (글자 수 같음, 11/6 측정) → GPU 기본은 int8_float16
COMPUTE = os.environ.get("STT_COMPUTE_TYPE", "int8_float16" if DEVICE == "cuda" else "int8")
NO_SPEECH = 0.6          # 임시: 이보다 '말 아님' 확률이 높고 확신이 낮은 구간은 버린다
# 11/12 비교 측정(bench/, 엑셀 'STT 비교'): 회사·기술 용어 힌트 + 자막류 환각 거르기로 내 목소리 CER 7.4% → 5.8%, 용어 인식 79% → 91%
# (GPU·속도 그대로). 힌트는 시험 문장에 맞춘 게 아니라 회사 이름 + 백엔드 면접에 흔한 용어. 질문마다 그 질문의 핵심어를 더한다
HINT_WORDS = ("새벽소프트 API REST JWT OAuth Redis Kafka RabbitMQ Celery Docker Kubernetes 파드 GitHub Actions CI/CD Elasticsearch "
              "Slack PostgreSQL MySQL 인덱스 트랜잭션 Read Committed 낙관적 락 캐시 p95 p99 N+1 조인 React useMemo TypeScript "
              "Spring FastAPI Django BM25 RRF 리랭커 벡터 검색 LLM RAG 마이크로서비스 웹훅 HttpOnly 쿠키")
JUNK = re.compile(r"자막|시청해 ?주셔서|구독|좋아요|아멘|MBC|KBS|SBS")   # Whisper가 답변 끝 무음에 지어내는 문구 (유튜브 자막 학습 흔적)

celery = Celery("stt", broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"),
                backend=os.environ.get("REDIS_URL", "redis://redis:6379/0"))   # 연습 면접은 결과를 기다려 받는다 (11/12). 실제 답변은 link로 이어짐
celery.conf.result_expires = 600
celery.conf.worker_prefetch_multiplier = 1
_model = None


def model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        _model = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE)
    return _model


def _f0(x: np.ndarray, sr: int = 16000) -> float | None:
    """구간 목소리 높이(Hz): 30ms 창마다 자기상관 최댓값(75~400Hz)의 중앙값. 소리가 작은 창은 뺀다"""
    n, out = int(sr * 0.03), []
    for i in range(0, len(x) - n, n):
        w = x[i:i + n] - x[i:i + n].mean()
        if np.sqrt((w ** 2).mean()) < 0.01:
            continue
        ac = np.correlate(w, w, "full")[n - 1:]
        lo, hi = sr // 400, sr // 75
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.3 * ac[0]:
            out.append(sr / k)
    return round(float(np.median(out)), 1) if out else None


def tone(audio_path: str, segs: list) -> list[dict]:
    """문장 구간마다 목소리 표기 (임시 규칙, 점수에 안 씀): 음량(dBFS)·높낮이·말 빠르기(글자/초)·앞 쉼.
    기준은 그 답변 안의 평균 (사람마다 목소리가 달라서)
    '작은 목소리' 표기는 뺐다 (11/16): 직접 녹음 비교에서 일부러 작게 말해도 보통보다 2.6dB만 작고 자신 있게·망설이며보다 커서
    음량으로는 가릴 수 없었다 (엑셀 '목소리 톤 비교'). 마이크에 안 잡힐 만큼 작으면 STT가 비어 응답 상태로 처리된다"""
    from faster_whisper import decode_audio
    x, sr = decode_audio(audio_path), 16000
    rows, prev_end = [], 0.0
    for s in segs:
        w = x[int(s.start * sr):int(s.end * sr)]
        rms = float(np.sqrt((w ** 2).mean())) if len(w) else 0.0
        rows.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(), "db": round(20 * np.log10(rms + 1e-9), 1),
                     "f0": _f0(w), "cps": round(len(s.text.strip().replace(" ", "")) / max(s.end - s.start, 0.3), 1),
                     "pause": round(max(0.0, s.start - prev_end), 2)})
        prev_end = s.end
    mean_db = float(np.mean([r["db"] for r in rows])) if rows else 0.0
    for r in rows:
        if r["pause"] >= 1.5 or r["cps"] < 3:
            r["label"] = "망설임"
        elif r["cps"] > 8:
            r["label"] = "빠른 말"
        elif r["db"] >= mean_db + 1:
            r["label"] = "자신감 있는 목소리"
        else:
            r["label"] = "차분한 목소리"
    return rows


@celery.task(name="stt.transcribe")
def transcribe(audio_key: str, hints: str = "") -> dict:
    """→ {"text": str | None, "segments": [구간별 글·목소리 표기], "sec": 처리 초, "model": 이름} 또는 {"error": ...}. 말이 없으면 text None.
    hints: 그 질문의 핵심어 (worker가 넘김)"""
    t0 = time.monotonic()
    try:
        path = os.path.join(os.environ.get("AUDIO_DIR", "/audio"), audio_key)
        segs, _ = model().transcribe(path, language="ko", beam_size=5, vad_filter=True, condition_on_previous_text=False,
                                     hotwords=f"{HINT_WORDS} {hints}".strip())
        segs = [s for s in segs if not (s.no_speech_prob > NO_SPEECH and s.avg_logprob < -1.0)]
        cut = next((i for i, s in enumerate(segs) if JUNK.search(s.text)), None)
        if cut is not None:                     # 자막류 문구가 나온 구간부터 뒤는 버린다 (그 구간 앞부분은 문구 앞까지만)
            head = JUNK.split(segs[cut].text)[0].strip()
            segs = segs[:cut] + ([dataclasses.replace(segs[cut], text=head)] if head else [])
        text = " ".join(s.text.strip() for s in segs).strip()
        try:
            segments = tone(path, segs) if segs else []
        except Exception:                       # noqa: BLE001  목소리 표기는 참고용이라 실패해도 글은 넘긴다
            segments = []
        return {"text": text or None, "segments": segments, "sec": round(time.monotonic() - t0, 2), "model": f"faster-whisper {MODEL}"}
    except Exception as e:                      # 파일 깨짐·GPU 오류 → worker가 시스템 오류로 처리
        return {"error": f"{type(e).__name__}: {str(e)[:300]}", "model": f"faster-whisper {MODEL}"}


@celery.on_after_finalize.connect
def _warm(sender, **_):
    model()                                     # 첫 답변이 모델 적재(수십 초)를 기다리지 않게 시작할 때 올려 둔다
