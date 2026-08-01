FROM flink:1.20.1-scala_2.12-java17 AS flink-client

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLINK_HOME=/opt/flink \
    PATH=/opt/flink/bin:${PATH} \
    PYTHONPATH=/app:/app/streaming/flink \
    PYFLINK_CLIENT_EXECUTABLE=/opt/pyflink-venv/bin/python
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    openjdk-17-jre-headless \
    python3.11 \
    python3.11-venv \
    supervisor \
    && rm -rf /var/lib/apt/lists/*
COPY --from=flink-client /opt/flink /opt/flink
RUN curl -fsSL \
    -o /opt/flink/lib/flink-sql-connector-kafka-3.3.0-1.20.jar \
    https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.3.0-1.20/flink-sql-connector-kafka-3.3.0-1.20.jar
RUN /usr/bin/python3.11 -m venv /opt/pyflink-venv \
    && /opt/pyflink-venv/bin/pip install --no-cache-dir apache-flink==1.20.1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY .env.example .env
RUN chmod +x entrypoint.sh scripts/ensure_flink_jobs.py
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1:${PORT:-8000}/healthz || exit 1
ENTRYPOINT ["./entrypoint.sh"]
