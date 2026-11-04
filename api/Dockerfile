# api (단계 3부터 worker도 같은 이미지). 버전은 requirements/api.lock.txt 고정 그대로
FROM python:3.12-slim
WORKDIR /app
COPY requirements/api.lock.txt requirements/dev.in /tmp/req/
RUN pip install --no-cache-dir -r /tmp/req/api.lock.txt -r /tmp/req/dev.in
# pgserver(시험용 임시 PostgreSQL)는 root로 initdb를 못 하므로 일반 사용자로 실행
RUN useradd -m app && mkdir /audio /photos && chown app /audio /photos   # 답변 음성 임시 볼륨 · 지원서 증명사진 (11/10)
USER app
