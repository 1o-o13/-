# 면접관 음성 (Supertonic 1.3.1, CPU) · Python 3.12
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 HF_HOME=/models
COPY requirements/tts.lock.txt /tmp/tts.lock.txt
RUN pip install --no-cache-dir -r /tmp/tts.lock.txt
WORKDIR /app
COPY tts/app.py /app/app.py
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
