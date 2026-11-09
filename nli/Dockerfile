# CE(bge-reranker-v2-m3)·NLI(mDeBERTa-v3-base-xnli) 판정 서버 (CPU) · Python 3.12. 버전은 requirements/nli.lock.txt 고정
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 HF_HOME=/models
COPY requirements/nli.lock.txt /tmp/nli.lock.txt
RUN pip install --no-cache-dir -r /tmp/nli.lock.txt
WORKDIR /app
COPY nli/app.py /app/app.py
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
