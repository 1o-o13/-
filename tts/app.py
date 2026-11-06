"""면접관 음성 (Supertonic 1.3.1, CPU). POST /speak {"text"} → 한국어 WAV. api만 부른다 (지원자 브라우저는 api를 거쳐 받음).
모델은 처음 실행 때 HF에서 내려받아 /models 볼륨에 둔다 (다음부터는 그대로 씀).
"""
import os
import tempfile
import threading

from fastapi import FastAPI, Response
from pydantic import BaseModel, Field
from supertonic import TTS

MODEL = os.environ.get("TTS_MODEL", "supertonic-3")
VOICE = os.environ.get("TTS_VOICE", "F1")          # 임시: 면접관 목소리 (M1~M5·F1~F5), 팀 결정 전
SPEED = float(os.environ.get("TTS_SPEED", "1.0"))  # 임시: 질문은 조금 또박또박 (기본 1.05)

app = FastAPI()
_tts: TTS | None = None
_lock = threading.Lock()                            # onnxruntime 세션 하나를 여러 요청이 동시에 쓰지 않게


def engine() -> TTS:
    global _tts
    if _tts is None:
        _tts = TTS(model=MODEL)
    return _tts


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@app.get("/health")
def health():
    engine()
    return {"model": MODEL, "voice": VOICE}


@app.post("/speak")
def speak(body: SpeakIn):
    with _lock:
        t = engine()
        wav, _ = t.synthesize(body.text, voice_style=t.get_voice_style(VOICE), speed=SPEED, lang="ko")
        with tempfile.NamedTemporaryFile(suffix=".wav") as f:
            t.save_audio(wav, f.name)
            data = open(f.name, "rb").read()
    return Response(data, media_type="audio/wav")
