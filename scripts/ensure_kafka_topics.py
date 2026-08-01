#!/usr/bin/env python3
"""Create required Kafka topics when they do not already exist."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from confluent_kafka import KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


DEFAULT_TOPICS = (
    "market.raw.v1",
    "market.canonical.v1",
    "market.bars.v1",
    "market.indicators.v1",
    "market.quality.v1",
    "instrument.registry.v1",
    "strategy.inputs.v1",
    "strategy.targets.v1",
    "portfolio.rebalance.planned.v1",
    "risk.decisions.v1",
    "orders.events.v1",
    "executions.events.v1",
    "reconciliation.events.v1",
    "system.health.v1",
    "dead-letter.v1",
)


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def positive_integer(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be a valid integer"
        ) from exc

    if value < 1:
        raise RuntimeError(
            f"{name} must be greater than zero"
        )

    return value


def required_topics() -> tuple[str, ...]:
    configured = os.getenv(
        "EXECUTION_REQUIRED_KAFKA_TOPICS",
        "",
    ).strip()

    if not configured:
        return DEFAULT_TOPICS

    topics = tuple(
        topic.strip()
        for topic in configured.split(",")
        if topic.strip()
    )

    if not topics:
        raise RuntimeError(
            "EXECUTION_REQUIRED_KAFKA_TOPICS is empty"
        )

    return topics


def ensure_kafka_topics() -> None:
    if not env_bool("KAFKA_ENABLED", False):
        print(
            "Kafka is disabled; skipping topic bootstrap.",
            flush=True,
        )
        return

    bootstrap_servers = os.getenv(
        "KAFKA_BOOTSTRAP_SERVERS",
        "",
    ).strip()

    if not bootstrap_servers:
        raise RuntimeError(
            "KAFKA_BOOTSTRAP_SERVERS is not configured"
        )

    if "://" in bootstrap_servers:
        raise RuntimeError(
            "KAFKA_BOOTSTRAP_SERVERS must not contain "
            "http:// or https://"
        )

    partitions = positive_integer(
        "KAFKA_TOPIC_PARTITIONS",
        3,
    )

    replication_factor = positive_integer(
        "KAFKA_TOPIC_REPLICATION_FACTOR",
        1,
    )

    max_attempts = positive_integer(
        "KAFKA_BOOTSTRAP_MAX_ATTEMPTS",
        30,
    )

    retry_seconds = positive_integer(
        "KAFKA_BOOTSTRAP_RETRY_SECONDS",
        2,
    )

    admin_timeout = positive_integer(
        "KAFKA_ADMIN_TIMEOUT_SECONDS",
        15,
    )

    topics = required_topics()

    admin = AdminClient(
        {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "trading-engine-topic-bootstrap",
            "socket.timeout.ms": admin_timeout * 1000,
            "request.timeout.ms": admin_timeout * 1000,
        }
    )

    for attempt in range(1, max_attempts + 1):
        try:
            metadata = admin.list_topics(
                timeout=admin_timeout
            )

            existing_topics = set(metadata.topics)
            missing_topics = [
                topic
                for topic in topics
                if topic not in existing_topics
            ]

            if not missing_topics:
                print(
                    "All required Kafka topics already exist.",
                    flush=True,
                )
                return

            print(
                "Creating Kafka topics: "
                + ", ".join(missing_topics),
                flush=True,
            )

            topic_requests = [
                NewTopic(
                    topic=topic,
                    num_partitions=partitions,
                    replication_factor=replication_factor,
                )
                for topic in missing_topics
            ]

            futures = admin.create_topics(
                topic_requests,
                operation_timeout=admin_timeout,
                request_timeout=admin_timeout,
            )

            for topic, future in futures.items():
                try:
                    future.result(timeout=admin_timeout)

                except KafkaException as exc:
                    kafka_error = (
                        exc.args[0]
                        if exc.args
                        else None
                    )

                    if (
                        kafka_error is not None
                        and kafka_error.code()
                        == KafkaError.TOPIC_ALREADY_EXISTS
                    ):
                        print(
                            f"Kafka topic '{topic}' "
                            "already exists.",
                            flush=True,
                        )
                        continue

                    raise

                else:
                    print(
                        f"Created Kafka topic '{topic}'.",
                        flush=True,
                    )

            verification = admin.list_topics(
                timeout=admin_timeout
            )

            unresolved_topics = [
                topic
                for topic in topics
                if topic not in verification.topics
            ]

            if unresolved_topics:
                raise RuntimeError(
                    "Kafka did not expose the following topics "
                    "after creation: "
                    + ", ".join(unresolved_topics)
                )

            print(
                "Kafka topic bootstrap completed.",
                flush=True,
            )
            return

        except Exception as exc:
            if attempt == max_attempts:
                raise RuntimeError(
                    "Kafka topic bootstrap failed after "
                    f"{max_attempts} attempts: {exc}"
                ) from exc

            print(
                f"Kafka topic bootstrap failed: {exc}. "
                f"Retrying in {retry_seconds} seconds "
                f"({attempt}/{max_attempts}).",
                file=sys.stderr,
                flush=True,
            )

            time.sleep(retry_seconds)


if __name__ == "__main__":
    ensure_kafka_topics()