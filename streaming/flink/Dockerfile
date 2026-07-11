FROM flink:1.20.1-scala_2.12-java17
USER root
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip curl && rm -rf /var/lib/apt/lists/*
RUN ln -s /usr/bin/python3 /usr/local/bin/python
COPY requirements.txt /tmp/requirements.txt
RUN pip3 install --no-cache-dir -r /tmp/requirements.txt
RUN curl -fsSL -o /opt/flink/lib/flink-sql-connector-kafka-3.3.0-1.20.jar https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/3.3.0-1.20/flink-sql-connector-kafka-3.3.0-1.20.jar
COPY jobs /opt/flink/usrlib/jobs
COPY entrypoint.sh /opt/flink/finflock-entrypoint.sh
ENV PYTHONPATH=/opt/flink/usrlib
RUN sed -i 's/\r$//' /opt/flink/finflock-entrypoint.sh && chmod +x /opt/flink/finflock-entrypoint.sh && mkdir -p /opt/flink/checkpoints /opt/flink/savepoints && chown -R flink:flink /opt/flink/checkpoints /opt/flink/savepoints /opt/flink/usrlib
USER flink
ENTRYPOINT ["/opt/flink/finflock-entrypoint.sh"]
