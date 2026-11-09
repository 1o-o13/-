"""LangGraph 체크포인터 PostgresSaver (아키텍처 v0.1). 프로세스마다 연결 풀 하나를 늦게 만든다 (Celery fork 뒤).
체크포인트 테이블(checkpoints·checkpoint_writes·checkpoint_blobs·checkpoint_migrations)은 라이브러리가 만든다 (setup)."""
import os
import threading

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

_lock = threading.Lock()
_saver = None
# 프로세스마다 동시에 도는 그래프 실행 수 상한 (동시 접속 50명+, 11/10). 실행 하나가 DB 연결을 4개까지 겹쳐 쥐므로
# (잠금 + 노드 + 검색·호출 기록) 연결 풀 ≥ 요청 스레드(40) + GRAPH_MAX × 4 이면 풀끼리 서로 기다리며 막히지 않는다
GRAPH_MAX = int(os.environ.get("GRAPH_MAX", "8"))
gate = threading.BoundedSemaphore(GRAPH_MAX)


def saver():
    global _saver
    with _lock:
        if _saver is None:
            from langgraph.checkpoint.postgres import PostgresSaver
            pool = ConnectionPool(os.environ["DATABASE_URL"], min_size=1, max_size=int(os.environ.get("CKPT_POOL_MAX", "20")), open=True, timeout=60,
                                  kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
            s = PostgresSaver(pool)
            s.setup()                                # 테이블이 없으면 만든다 (있으면 아무것도 안 함)
            _saver = s
    return _saver


def reset() -> None:
    """시험: DB를 새로 만들었을 때 다음 호출에서 다시 연결·setup"""
    global _saver
    with _lock:
        _saver = None
