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

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8111/health || exit 1

ENTRYPOINT ["python", "-m", "app.main"]
CMD ["--transport", "http"]
