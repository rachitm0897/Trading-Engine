# Kafka contracts

All topics are private infrastructure and use the versioned envelope in `schemas/event-envelope-v1.json`.
Decimal values are JSON strings, timestamps are UTC ISO-8601 values, and retries retain the original `event_id`.
Market topics are keyed by instrument, portfolio topics by portfolio, order topics by internal order ID, and execution/reconciliation topics by account.

Breaking changes create a new topic/schema version. Compatible optional fields may be added within v1.
`dead-letter.v1` retains the original envelope plus source topic, consumer and failure reason. Replay requests are audited in PostgreSQL and use a distinct consumer group; database uniqueness and `ConsumedEvent` protect side effects.
