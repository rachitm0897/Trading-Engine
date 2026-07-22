# Streaming subsystem

Kafka is durable transport, PyFlink owns continuous market transformations, and PostgreSQL remains authoritative for every financial fact. Neither Kafka nor Flink imports the OMS or Gateway and neither can place orders.

Flink jobs use stable names/operator UIDs, event-time watermarks, checkpoints and restart configuration. Submit jobs from inside the private network with `flink run -py /opt/flink/usrlib/jobs/<job>.py`; no Flink or Kafka port is published by Compose.
