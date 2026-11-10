# 얼굴 대조 (InsightFace buffalo_l, 11/16 — 그 전 DeepFace ArcFace) · Python 3.12. 버전은 requirements/face.lock.txt 고정 그대로. Celery 큐 'face'에서 작업을 받는다
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 DEEPFACE_HOME=/models INSIGHTFACE_HOME=/models/insightface CUDA_VISIBLE_DEVICES=-1 TF_CPP_MIN_LOG_LEVEL=2
RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 libgl1 && rm -rf /var/lib/apt/lists/*
COPY requirements/face.lock.txt /tmp/face.lock.txt
RUN pip install --no-cache-dir -r /tmp/face.lock.txt
# 11/16 본인 확인 모델 InsightFace buffalo_l (requirements/face.extra.lock.txt 설명 참고: 기존 고정 버전을 바꾸지 않게 --no-deps)
COPY requirements/face.extra.lock.txt /tmp/face.extra.lock.txt
RUN pip install --no-cache-dir --no-deps -r /tmp/face.extra.lock.txt
WORKDIR /app
COPY face/app.py /app/app.py
CMD ["celery", "-A", "app", "worker", "-Q", "face", "--loglevel=info", "--concurrency=2"]
