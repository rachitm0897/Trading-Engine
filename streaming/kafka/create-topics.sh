#!/bin/bash
set -euo pipefail

for topic in market.raw.v1 market.canonical.v1 market.bars.v1 market.indicators.v1 market.quality.v1 strategy.inputs.v1 strategy.targets.v1 portfolio.flow.allocated.v1 portfolio.rebalance.planned.v1 risk.decisions.v1 orders.events.v1 executions.events.v1 reconciliation.events.v1 system.health.v1 dead-letter.v1; do
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic "$topic" --partitions 6 --replication-factor 1
done

/opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic instrument.registry.v1 --partitions 6 --replication-factor 1 --config cleanup.policy=compact
