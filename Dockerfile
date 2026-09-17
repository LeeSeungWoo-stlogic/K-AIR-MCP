# 패치 버전까지 고정한다. 폐쇄망 반입은 빌드한 이미지를 docker save / docker load 로 옮긴다(현장에서 pull·빌드하지 않음).
FROM python:3.11.9-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ENV TIBERO_JDBC_JAR=/opt/tibero/jdbc/tibero-jdbc.jar

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
# driver/ 디렉터리째 복사한다. tibero-jdbc.jar 가 없어도(README.md 만 있어도) 빌드는 된다.
# JAR 이 없으면 Tibero 도구만 "Tibero JDBC 드라이버 미탑재" 오류를 돌려준다.
COPY driver/ /opt/tibero/jdbc/

EXPOSE 8111

# /health 는 의존 서비스를 부르지 않는 생존 확인이다. 의존 확인은 /health/ready (503 가능).
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -fsS --max-time 2 http://127.0.0.1:8111/health || exit 1

ENTRYPOINT ["python", "-m", "app.main"]
CMD ["--transport", "http"]
