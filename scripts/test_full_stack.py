"""전체 시스템 버전 세트 실행 점검 (기능정의서 기준). Python 3.12에서 `pytest -q scripts/test_full_stack.py`.

설치만 되고 실행에서 깨지는 문제를 잡으려고 기능마다 작은 실제 동작을 해 본다.
외부 서비스(Ollama 서버, SMTP, OAuth 제공사, Judge0)는 부르지 않고, 로컬 대체물이나 가짜 모델로 확인한다.
pgvector 시험은 pgserver(시험 전용, 운영에는 쓰지 않음)가 있으면 실제 PostgreSQL로 돈다.
"""
import asyncio
import io
import os
import socket
import tempfile

import pytest


# ---------- 공통 백엔드 (모든 파트) ----------
def test_fastapi_pydantic_sqlalchemy():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import BaseModel, EmailStr
    from sqlalchemy import JSON, String, create_engine, select
    from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

    class Base(DeclarativeBase):
        pass

    class Applicant(Base):
        __tablename__ = "applicant"
        id: Mapped[int] = mapped_column(primary_key=True)
        email: Mapped[str] = mapped_column(String)
        meta: Mapped[dict] = mapped_column(JSON)

    from sqlalchemy.pool import StaticPool

    # 메모리 DB를 요청 처리 스레드와 공유하려고 StaticPool 사용 (운영은 PostgreSQL)
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)

    class In(BaseModel):
        email: EmailStr

    app = FastAPI()

    @app.post("/apply")
    def apply(x: In):
        with Session(eng) as s:
            s.add(Applicant(email=x.email, meta={"stage": "서류"}))
            s.commit()
            return {"n": len(s.scalars(select(Applicant)).all())}

    c = TestClient(app)
    assert c.post("/apply", json={"email": "a@example.com"}).json() == {"n": 1}
    assert c.post("/apply", json={"email": "bad"}).status_code == 422


# ---------- 인증: 로그인·2단계 인증·소셜 로그인·접속 제한 (F-ADM-01·27, F-CAN-03·04) ----------
def test_auth_jwt_bcrypt_totp():
    import bcrypt
    import jwt
    import pyotp

    key = "k" * 32
    assert jwt.decode(jwt.encode({"sub": "1"}, key, algorithm="HS256"), key, algorithms=["HS256"])["sub"] == "1"
    assert bcrypt.checkpw(b"pw", bcrypt.hashpw(b"pw", bcrypt.gensalt()))
    t = pyotp.TOTP(pyotp.random_base32())
    assert t.verify(t.now())


def test_social_login_client_and_session():
    from authlib.integrations.starlette_client import OAuth
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from starlette.middleware.sessions import SessionMiddleware  # itsdangerous 필요

    oauth = OAuth()
    oauth.register("kakao", client_id="x", client_secret="y",
                   authorize_url="https://kauth.kakao.com/oauth/authorize",
                   access_token_url="https://kauth.kakao.com/oauth/token")
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="s" * 32)

    @app.get("/login")
    async def login(request: Request):
        return await oauth.kakao.authorize_redirect(request, "http://testserver/cb")

    r = TestClient(app).get("/login", follow_redirects=False)
    assert r.status_code == 302 and "kauth.kakao.com" in r.headers["location"]


def test_rate_limit_login():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    @app.post("/login")
    @limiter.limit("2/minute")
    def login(request: Request):
        return {"ok": True}

    c = TestClient(app)
    codes = [c.post("/login").status_code for _ in range(3)]
    assert codes == [200, 200, 429]


# ---------- 알림: 메일 발송·자동 안내 예약 (F-ADM-24·41·76) ----------
def test_mail_send_to_local_smtp():
    from aiosmtpd.controller import Controller
    from fastapi_mail import ConnectionConfig, FastMail, MessageSchema, MessageType

    got = []

    class H:
        async def handle_DATA(self, server, session, envelope):
            got.append(envelope.content.decode("utf-8", "ignore"))
            return "250 OK"

    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    ctl = Controller(H(), hostname="127.0.0.1", port=port)
    ctl.start()
    try:
        conf = ConnectionConfig(MAIL_USERNAME="", MAIL_PASSWORD="", MAIL_FROM="hr@example.com", MAIL_PORT=port,
                                MAIL_SERVER="127.0.0.1", MAIL_STARTTLS=False, MAIL_SSL_TLS=False,
                                USE_CREDENTIALS=False, VALIDATE_CERTS=False)
        msg = MessageSchema(subject="결과 발표 안내", recipients=["a@example.com"],
                            body="<p>채용 사이트에서 결과를 확인해 주세요.</p>", subtype=MessageType.html)
        asyncio.run(FastMail(conf).send_message(msg))
    finally:
        ctl.stop()
    assert got and "a@example.com" in got[0]


def test_celery_task_and_beat_schedule():
    from celery import Celery
    from celery.schedules import crontab

    app = Celery("t", broker="memory://", backend="cache+memory://")
    app.conf.task_always_eager = True
    app.conf.beat_schedule = {"마감전안내": {"task": "remind", "schedule": crontab(hour=9, minute=0)},
                              "보관기간삭제": {"task": "purge", "schedule": crontab(hour=3, minute=0)}}

    @app.task(name="remind")
    def remind(n):
        return n * 2

    assert remind.delay(21).get() == 42


# ---------- 문서: 지원서 PDF·합격자 명단 PDF·이력서 파일 읽기 (F-CAN-13, F-ADM-43·63) ----------
def test_pdf_korean_and_read_back():
    from pypdf import PdfReader
    from weasyprint import HTML

    html = "<html><body style='font-family: \"Noto Sans CJK KR\", sans-serif'><h1>지원서</h1><p>홍길동 · 백엔드 개발</p></body></html>"
    pdf = HTML(string=html).write_pdf()
    text = PdfReader(io.BytesIO(pdf)).pages[0].extract_text()
    assert "지원서" in text, text


def test_docx_resume_read():
    from docx import Document

    d = Document(); d.add_paragraph("경력: 3년 · Python")
    buf = io.BytesIO(); d.save(buf); buf.seek(0)
    assert "Python" in Document(buf).paragraphs[0].text


# ---------- AI: 무료 버전 — 모든 LLM·임베딩을 온프레미스 Ollama로 (유료 Claude·OpenAI는 requirements/paid) ----------
# 실제 Ollama 서버 대신, 같은 HTTP API(/api/chat, /api/embed)를 흉내 내는 로컬 서버로 클라이언트 코드 전체를 돌려 본다.
# 모델 파일 실행 확인은 GPU 서버에서 scripts/check_ollama.py로 한다.
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EVAL_MODEL, FAST_MODEL, EMBED_MODEL, EMBED_DIM = "qwen3:4b", "qwen3:1.7b", "bge-m3", 1024


def _vec(text):
    import math
    h = hashlib.sha256(text.encode()).digest()
    v = [((h[i % 32] + i * 7) % 251) / 250 - 0.5 for i in range(EMBED_DIM)]
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


@pytest.fixture(scope="module")
def fake_ollama():
    seen = []
    slow = {"models": set(), "sec": 0.0}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, req))
            if self.path == "/api/embed":
                inp = req["input"] if isinstance(req["input"], list) else [req["input"]]
                return self._send({"model": req["model"], "embeddings": [_vec(t) for t in inp]})
            if self.path == "/api/chat":
                if req["model"] in slow["models"]:
                    time.sleep(slow["sec"])
                if req.get("format"):
                    content = json.dumps({"judgement": "보통", "rationale": "핵심 개념을 맞게 설명함"}, ensure_ascii=False)
                else:
                    content = "보통"
                msg = {"model": req["model"], "created_at": "2026-11-01T00:00:00Z",
                       "message": {"role": "assistant", "content": content}, "done": True, "done_reason": "stop",
                       "prompt_eval_count": 10, "eval_count": 5}
                if req.get("stream", True):
                    body = (json.dumps(msg, ensure_ascii=False) + "\n").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                return self._send(msg)
            self.send_error(404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield {"url": f"http://127.0.0.1:{srv.server_port}", "seen": seen, "slow": slow}
    srv.shutdown()


def test_ollama_structured_judgement(fake_ollama):
    """면접 답변 판정(F-AI-04): 정해진 형식(JSON 스키마)으로 받기."""
    from typing import Literal

    from langchain_ollama import ChatOllama
    from pydantic import BaseModel

    class Judgement(BaseModel):
        judgement: Literal["우수", "보통", "미흡", "무응답"]
        rationale: str

    llm = ChatOllama(model=EVAL_MODEL, base_url=fake_ollama["url"], temperature=0)
    out = llm.with_structured_output(Judgement, method="json_schema").invoke("답변: 인덱스는 B-트리로 ...")
    assert out.judgement == "보통" and out.rationale
    path, req = fake_ollama["seen"][-1]
    assert path == "/api/chat" and req["model"] == EVAL_MODEL
    assert req["format"]["properties"]["judgement"]["enum"] == ["우수", "보통", "미흡", "무응답"]


def test_llm_wait_rule_30s_fallback_60s_error(fake_ollama):
    """대기 규칙: 30초 넘으면 빠른 모델로, 60초 넘으면 시스템 오류. 시험은 1/100 축소(0.3초·0.6초)."""
    import httpx
    from langchain_ollama import ChatOllama

    T1, T2 = 0.3, 0.6

    def judge(prompt):
        t0 = time.monotonic()
        try:
            r = ChatOllama(model=EVAL_MODEL, base_url=fake_ollama["url"], client_kwargs={"timeout": T1}).invoke(prompt)
            return "eval", r.content
        except (httpx.TimeoutException, TimeoutError):
            left = T2 - (time.monotonic() - t0)
            try:
                r = ChatOllama(model=FAST_MODEL, base_url=fake_ollama["url"], client_kwargs={"timeout": left}).invoke(prompt)
                return "fast", r.content
            except (httpx.TimeoutException, TimeoutError):
                return "system_error", None

    slow = fake_ollama["slow"]
    slow.update(models=set(), sec=0)
    assert judge("q") == ("eval", "보통")
    slow.update(models={EVAL_MODEL}, sec=0.5)
    assert judge("q") == ("fast", "보통")
    slow.update(models={EVAL_MODEL, FAST_MODEL}, sec=0.5)
    assert judge("q")[0] == "system_error"
    slow.update(models=set(), sec=0)


def test_langgraph_with_ollama(fake_ollama):
    from typing import TypedDict

    from langchain_core.prompts import ChatPromptTemplate
    from langchain_ollama import ChatOllama
    from langgraph.graph import END, StateGraph

    chain = ChatPromptTemplate.from_messages([("user", "{q}")]) | ChatOllama(model=EVAL_MODEL, base_url=fake_ollama["url"])

    class S(TypedDict):
        q: str
        out: str

    g = StateGraph(S)
    g.add_node("judge", lambda s: {"out": chain.invoke({"q": s["q"]}).content})
    g.set_entry_point("judge"); g.add_edge("judge", END)
    assert g.compile().invoke({"q": "질문", "out": ""})["out"] == "보통"


def test_ollama_embeddings_pgvector_1024(fake_ollama):
    """FAQ 검색(F-CAN-16): bge-m3(또는 KURE-v1) 1024차원 → pgvector."""
    pgserver = pytest.importorskip("pgserver")
    from langchain_ollama import OllamaEmbeddings
    from langchain_postgres import PGVector

    emb = OllamaEmbeddings(model=EMBED_MODEL, base_url=fake_ollama["url"])
    assert len(emb.embed_query("결과 발표는 언제인가요")) == EMBED_DIM
    d = tempfile.mkdtemp()
    srv = pgserver.get_server(d, cleanup_mode="stop")
    try:
        srv.psql("CREATE EXTENSION IF NOT EXISTS vector;")
        uri = srv.get_uri().replace("postgresql://", "postgresql+psycopg://")
        store = PGVector(embeddings=emb, collection_name="faq", connection=uri, embedding_length=EMBED_DIM)
        store.add_texts(["응시 중 화면이 멈췄어요", "결과 발표는 언제인가요", "비밀번호를 잊었어요"])
        assert store.similarity_search("결과 발표는 언제인가요", k=1)[0].page_content == "결과 발표는 언제인가요"
        typ = srv.psql("SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='langchain_pg_embedding'::regclass AND attname='embedding';")
        assert "vector(1024)" in typ
    finally:
        srv.cleanup()


def test_text_splitter():
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    parts = RecursiveCharacterTextSplitter(chunk_size=20, chunk_overlap=0).split_text("FAQ 답변 " * 20)
    assert len(parts) > 1


# ---------- 표절 탐지 (F-SYS-02) ----------
def test_plagiarism_similarity():
    from rapidfuzz import fuzz

    a = "def solve(n):\n    return sum(range(n))"
    b = "def solve(m):\n    return sum(range(m))"
    assert fuzz.ratio(a, b) > 90


# ---------- 진행 상태 실시간 전달 (SSE) ----------
def test_sse_stream():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sse_starlette.sse import EventSourceResponse

    app = FastAPI()

    @app.get("/events")
    async def events():
        async def gen():
            for step in ("stt", "judge", "done"):
                yield {"event": "progress", "data": step}
        return EventSourceResponse(gen())

    with TestClient(app).stream("GET", "/events") as r:
        body = "".join(r.iter_text())
    assert "data: done" in body


# ---------- 운영 모니터링 (F-ADM-26) ----------
def test_prometheus_metrics():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from prometheus_fastapi_instrumentator import Instrumentator

    app = FastAPI()
    Instrumentator().instrument(app).expose(app)
    c = TestClient(app)
    c.get("/metrics")
    assert "http_request" in c.get("/metrics").text


# ---------- 파일 저장소 (S3 호환) ----------
def test_boto3_client():
    import boto3

    c = boto3.client("s3", endpoint_url="http://storage:3900", aws_access_key_id="x", aws_secret_access_key="y",
                     region_name="garage")
    url = c.generate_presigned_url("get_object", Params={"Bucket": "resume", "Key": "a.pdf"}, ExpiresIn=60)
    assert "resume/a.pdf" in url


# ---------- 화상면접 (GPU 서버 패키지. api 환경에는 없으므로 건너뜀, 자세한 점검은 check_env.py) ----------
def test_interview_stack_imports():
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
    av = pytest.importorskip("av")
    pytest.importorskip("faster_whisper")
    pytest.importorskip("deepface")
    import werkzeug  # noqa: F401
    from deepface import DeepFace  # noqa: F401

    assert int(av.__version__.split(".")[0]) < 18
