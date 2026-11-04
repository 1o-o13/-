"""설치한 환경이 버전 호환표대로 동작하는지 점검한다. (2026-10-29 검증 기준, 팀원 버전 기준 통합안)

사용:  python scripts/check_env.py api      # 일반 서버 api·llm-worker
       python scripts/check_env.py stt      # GPU 서버 stt-worker
       python scripts/check_env.py face     # GPU 서버 face-worker (--arcface 를 붙이면 모델까지 생성)
       python scripts/check_env.py all

설치만 되고 실행에서 깨지는 문제(PyAV 19, DeepFace의 werkzeug 등)를 잡으려고, 불러오기와 작은 실제 동작까지 해 본다.
GPU가 있으면 GPU 인식 여부도 출력한다.
"""
import os
import sys
import tempfile

OK, FAIL = "OK  ", "FAIL"
results = []


def check(name, fn):
    try:
        msg = fn()
        results.append((OK, name, msg or ""))
    except Exception as e:  # 점검 스크립트라 모든 오류를 모아서 보여 준다
        results.append((FAIL, name, f"{type(e).__name__}: {str(e)[:160]}"))


def py_version():
    v = sys.version_info
    if (v.major, v.minor) != (3, 12):
        raise RuntimeError(f"Python {v.major}.{v.minor} — 팀 표준은 3.12")
    return f"{v.major}.{v.minor}.{v.micro}"


def api():
    import bcrypt, boto3, celery, fastapi, jwt, psycopg, pydantic, pyotp, redis, sqlalchemy  # noqa: F401
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import BaseModel
    from sqlalchemy import JSON, String, create_engine
    from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

    class Base(DeclarativeBase):
        pass

    class Answer(Base):
        __tablename__ = "answer"
        id: Mapped[int] = mapped_column(primary_key=True)
        stt: Mapped[str] = mapped_column(String)
        meta: Mapped[dict] = mapped_column(JSON)

    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Answer(stt="테스트", meta={"judgement": "우수"}))
        s.commit()

    class In(BaseModel):
        q: str

    app = FastAPI()

    @app.post("/t")
    def t(x: In):
        return {"q": x.q}

    assert TestClient(app).post("/t", json={"q": "a"}).json() == {"q": "a"}
    jwt.decode(jwt.encode({"a": 1}, "k", algorithm="HS256"), "k", algorithms=["HS256"])
    assert bcrypt.checkpw(b"pw", bcrypt.hashpw(b"pw", bcrypt.gensalt()))
    pyotp.TOTP(pyotp.random_base32()).now()
    return (f"fastapi {fastapi.__version__} · pydantic {pydantic.__version__} · sqlalchemy {sqlalchemy.__version__} · "
            f"psycopg {psycopg.__version__} · celery {celery.__version__} · redis {redis.__version__} · boto3 {boto3.__version__}")


def stt():
    import av
    import ctranslate2
    import faster_whisper
    import numpy as np
    from faster_whisper.audio import decode_audio

    if int(av.__version__.split(".")[0]) >= 19:
        raise RuntimeError(f"PyAV {av.__version__} — faster-whisper 1.2.1과 충돌. pip install 'av<19'")
    # Chrome MediaRecorder와 같은 WebM/Opus 1초짜리 파일을 만들어 디코딩해 본다
    path = os.path.join(tempfile.mkdtemp(), "t.webm")
    out = av.open(path, "w", format="webm")
    st = out.add_stream("libopus", rate=48000)
    st.layout = "mono"
    sr = 48000
    pcm = (0.2 * np.sin(2 * np.pi * 440 * np.arange(sr) / sr) * 32767).astype("int16").reshape(1, -1)
    fr = av.AudioFrame.from_ndarray(pcm, format="s16", layout="mono")
    fr.sample_rate = sr
    for p in st.encode(fr):
        out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close()
    n = len(decode_audio(path))
    gpus = ctranslate2.get_cuda_device_count()
    return (f"faster-whisper {faster_whisper.__version__} · ctranslate2 {ctranslate2.__version__} · av {av.__version__} · "
            f"WebM/Opus 디코딩 {n} samples · CUDA GPU {gpus}개")


def face(build_arcface: bool):
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    os.environ.setdefault("TF_FORCE_GPU_ALLOW_GROWTH", "true")
    import tensorflow as tf
    import tf_keras  # noqa: F401
    import werkzeug  # noqa: F401  DeepFace가 쓰지만 의존성에 빠져 있음
    from deepface import DeepFace

    bi = tf.sysconfig.get_build_info()
    gpus = tf.config.list_physical_devices("GPU")
    msg = (f"tensorflow {tf.__version__} (CUDA {bi.get('cuda_version')} · cuDNN {bi.get('cudnn_version')}) · "
           f"GPU {len(gpus)}개 · TF_FORCE_GPU_ALLOW_GROWTH={os.environ['TF_FORCE_GPU_ALLOW_GROWTH']}")
    if build_arcface:
        import numpy as np
        DeepFace.build_model("ArcFace")  # 처음에는 가중치를 내려받는다(인터넷 필요)
        img = (np.random.rand(160, 160, 3) * 255).astype("uint8")
        emb = DeepFace.represent(img, model_name="ArcFace", enforce_detection=False, detector_backend="skip")
        msg += f" · ArcFace 특징값 {len(emb[0]['embedding'])}개"
    return msg


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "all"
    check("Python 버전", py_version)
    if role in ("api", "all"):
        check("api 스택", api)
    if role in ("stt", "all"):
        check("stt 스택", stt)
    if role in ("face", "all"):
        check("face 스택", lambda: face("--arcface" in sys.argv))
    for status, name, msg in results:
        print(f"[{status}] {name}: {msg}")
    sys.exit(1 if any(s == FAIL for s, _, _ in results) else 0)
