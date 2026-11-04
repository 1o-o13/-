"""api 시험 공용: pgserver 임시 DB에 스키마 + seed/test_data.sql을 넣고, 앱이 그 DB를 쓰게 한다 (개발 DB와 섞이지 않음)."""
import importlib.util
import os
import pathlib
import tempfile

import psycopg
import pytest
from fastapi.testclient import TestClient

os.environ["MODULE_MODE"] = "stub"   # 시험은 가짜 질문·판정 (LLM 비용·시간 없이, 결과 고정). 시험 파일이 api.modules를 import하기 전에

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


@pytest.fixture(scope="session")
def db_url():
    pgserver = pytest.importorskip("pgserver")
    srv = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="stop")
    url = srv.get_uri()
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        for f in ("db/common_schema.sql", "db/interview_schema.sql", "seed/test_data.sql"):
            c.execute(pathlib.Path(ROOT, f).read_text(encoding="utf-8"))
    old = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    spec = importlib.util.spec_from_file_location("load_corpus", os.path.join(ROOT, "scripts", "load_corpus.py"))
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    loader.main([os.path.join(ROOT, "seed", "corpus_6_1")])     # tasks.ps1 seed와 같은 문서
    from scripts import build_question_bank
    build_question_bank.main(url)                               # 직무별 질문 은행
    os.environ.setdefault("JWT_SECRET", "test-only-secret-at-least-32-bytes-long")
    os.environ["STT_MODE"] = os.environ["TTS_MODE"] = os.environ["FACE_MODE"] = "stub"   # 시험은 음성·얼굴 컨테이너 없이 (.env가 real이어도)
    os.environ["AUDIO_DIR"] = tempfile.mkdtemp()
    os.environ["PHOTO_DIR"] = tempfile.mkdtemp()   # 증명사진 (시험용 임시 폴더)
    from worker.app import celery
    celery.conf.task_always_eager = True       # 시험: worker 작업을 요청 안에서 바로 실행 (Redis 불필요)
    yield url
    if old is not None:
        os.environ["DATABASE_URL"] = old
    srv.cleanup()


@pytest.fixture
def client(db_url):
    from api.main import app
    with TestClient(app) as c:      # with: 시작 때 llm.check_config()까지 실행
        yield c
