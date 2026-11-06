# STT 작업자 (faster-whisper, GPU). CUDA 12 + cuDNN 9 (ctranslate2 4.8.4 요구) · Ubuntu 24.04 기본 Python 3.12
FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /venv
ENV PATH=/venv/bin:$PATH PYTHONUNBUFFERED=1 HF_HOME=/models
COPY requirements/stt.lock.txt /tmp/stt.lock.txt
RUN pip install --no-cache-dir -r /tmp/stt.lock.txt
WORKDIR /app
COPY stt/app.py /app/stt_app.py
# solo: 한 프로세스에서 처리 (GPU에 올린 모델은 fork한 자식 프로세스에서 쓸 수 없어 멈춤)
CMD ["celery", "-A", "stt_app", "worker", "-Q", "stt", "-P", "solo", "--loglevel", "info"]
