# Operational data retention

Retention applies only to reproducible or acknowledged operational records. Order intents, orders, status history, executions, fills, cash and position ledgers, reconciliation history, allocation decisions, strategy identity snapshots, and audit events are not deleted by compaction.

The backend Celery Beat task `compact-operational-records` runs daily and deletes at most `OPERATIONAL_COMPACTION_BATCH_SIZE` rows per category per run:

- Published outbox events after `OUTBOX_RETENTION_DAYS` (default 30). Pending, publishing, and failed events are retained.
- Successfully completed broker position snapshots after `BROKER_SNAPSHOT_RETENTION_DAYS` (default 30). Incomplete, processing, and failed snapshots are retained.
- Completed or terminal-error strategy readiness coordination rows after `READINESS_RETENTION_DAYS` (default 30). The related strategy run remains intact.
- Stream-health metric rows not refreshed for `STREAM_HEALTH_RETENTION_DAYS` (default 30). Active component/metric rows update in place and therefore remain retained.

The Gateway broker worker compacts at most `GATEWAY_COMPACTION_BATCH_SIZE` rows per category every `GATEWAY_COMPACTION_SECONDS` (default one hour):

- Acknowledged Gateway events after `GATEWAY_EVENT_RETENTION_DAYS` (default 7). Unacknowledged events are never selected.
- Gateway health snapshots after `GATEWAY_HEALTH_RETENTION_DAYS` (default 7). Current connection health remains in `GatewaySession`.

`StreamHealthMetric` normally contains one upserted current record per component and metric. The stale-row rule only removes metrics for components that have stopped reporting beyond the retention window.
