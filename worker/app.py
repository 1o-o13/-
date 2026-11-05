"""Celery 앱. api와 같은 이미지·같은 MODULE_MODE를 쓴다. 시험에서는 task_always_eager로 요청 안에서 바로 실행한다."""
import os

from celery import Celery
from celery.signals import worker_ready

celery = Celery("interview", broker=os.environ.get("REDIS_URL", "redis://redis:6379/0"), include=["worker.tasks"],
                backend=os.environ.get("REDIS_URL", "redis://redis:6379/0"))   # 결과 받기: 얼굴 대조(face.verify)를 요청 안에서 기다림 (11/10)
celery.conf.result_expires = 3600
# 매일 새벽 3시: 최종 발표 후 180일 지난 면접 기록 파기 (api/retention.py, 11/12). worker를 -B(beat 함께)로 띄운다
from celery.schedules import crontab  # noqa: E402
celery.conf.timezone = "Asia/Seoul"
celery.conf.beat_schedule = {"purge-interviews": {"task": "worker.tasks.purge_expired_interviews", "schedule": crontab(hour=3, minute=0)}}


@worker_ready.connect
def _warm(**_):
    """실제 모듈: BM25 형태소 분석기 첫 로딩(약 20초)을 미리 (꼬리질문 검색이 60초 안에 끝나게).
    worker는 스레드 방식이라 프로세스 하나에 한 번만 올린다 (11/10: 프로세스 16개가 따로 올려 메모리 6GB)"""
    if os.environ.get("MODULE_MODE") == "real":
        import threading

        from api import retrieve
        threading.Thread(target=retrieve.tokens, args=("준비",), daemon=True).start()
