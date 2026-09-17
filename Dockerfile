FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates default-jre-headless \
    && rm -rf /var/lib/apt/lists/*

ENV TIBERO_JDBC_JAR=/opt/tibero/jdbc/tibero-jdbc.jar

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY driver/tibero-jdbc.jar ${TIBERO_JDBC_JAR}

EXPOSE 8111

# /health 는 의존 서비스를 부르지 않는 생존 확인이다. 의존 확인은 /health/ready (503 가능).
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD curl -fsS --max-time 2 http://127.0.0.1:8111/health || exit 1

ENTRYPOINT ["python", "-m", "app.main"]
CMD ["--transport", "http"]
