# 코딩 테스트 채점 실행기. Python 3.12 + JDK 21 (eclipse-temurin에서 JDK만 복사). 바깥 패키지 없음
FROM python:3.12-slim
COPY --from=eclipse-temurin:21-jdk /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH=/opt/java/openjdk/bin:$PATH
RUN useradd -m judge
COPY judge/server.py /srv/server.py
USER judge
EXPOSE 8090
CMD ["python3", "-I", "/srv/server.py"]
