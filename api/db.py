"""psycopg 연결 (DATABASE_URL). 행은 dict로 받는다.
동시 접속 50명 이상(11/10): 요청마다 연결을 새로 열지 않고 프로세스마다 연결 풀 하나를 쓴다 (api 작업 프로세스·Celery 작업 프로세스마다,
fork 뒤 처음 쓸 때 만든다). `with connect() as db:`는 그대로 — 풀에서 빌려 쓰고 끝나면 돌려준다.
"""
import os
import threading

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

POOL_MAX = int(os.environ.get("DB_POOL_MAX", "20"))   # 임시: 프로세스당 최대 연결 (api 4 프로세스 + worker 16 → postgres max_connections 300)
_lock = threading.Lock()
_pool: dict[str, ConnectionPool] = {}


def _get() -> ConnectionPool:
    url = os.environ["DATABASE_URL"]
    with _lock:
        p = _pool.get(url)                          # 시험이 DB를 바꾸면 그 DB의 풀을 새로
        if p is None:
            p = ConnectionPool(url, min_size=1, max_size=POOL_MAX, open=True, timeout=60,
                               kwargs={"autocommit": True, "row_factory": dict_row})
            _pool[url] = p
    return p


def connect():
    return _get().connection()


def get_db():
    with connect() as conn:
        yield conn
