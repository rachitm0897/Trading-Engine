# Streaming subsystem

Kafka is durable transport, PyFlink owns continuous market transformations,
and PostgreSQL remains authoritative for every financial fact. Neither Kafka
nor Flink imports the OMS or Gateway and neither can place orders.

## Deterministic identities

Every identity is SHA-256 over canonical, sorted JSON. Kafka envelope IDs are
UUIDv5 values in the Finflock market namespace using
`<event-type>:<stable-key>`. Processing time, publication time, Kafka offset,
partition, and checkpoint attempt are never identity inputs.

| Event | Stable identity input |
| --- | --- |
| Raw | provider + provider generation + provider source event ID |
| Canonical | raw identity + canonical instrument ID |
| Bar | instrument ID + timeframe + UTC window start; event identity also includes correction version |
| Indicator | bar ID + bar version + full requirement identity + implementation version |
| Market quality | canonical source event ID + quality status |

The full indicator requirement identity contains input type, indicator name,
indicator role, canonical parameters, instrument ID, timeframe, and
implementation version. Two implementations or indicator names with equal
parameters therefore cannot collide.

## Restart, registry, and replay rules

Flink jobs use stable names/operator UIDs, event-time watermarks and
checkpoints. Normal Kafka inputs default to committed offsets and fall back to
latest only when a new consumer group has no committed position. Each job can
override this with `KAFKA_STARTING_OFFSETS_<NORMALIZED_JOB_NAME>` or the global
`KAFKA_STARTING_OFFSETS`; allowed values are `committed`, `earliest`, and
`latest`. Compacted registry inputs explicitly start at earliest so state can
be reconstructed.

Normalization keys raw and registry streams by conId. An unknown conId is held
in keyed state for `UNKNOWN_CONID_BUFFER_TIMEOUT_MS` (default 30 seconds), with
at most `UNKNOWN_CONID_BUFFER_MAX_EVENTS` events per conId. A registry update
releases buffered events. Capacity eviction or expiry emits one deterministic
DLQ event. Canonical deduplication state expires after
`DEDUPLICATION_STATE_TTL_SECONDS` (default 24 hours); the durable Backend event
identity remains the final replay boundary after that TTL.

Derived events carry one processing mode:

- `LIVE`: may schedule strategy evaluation after persistence and order checks.
- `WARMUP`: may seed rolling market history and warm-up counters, but never
  schedules strategy evaluation.
- `REPLAY`: uses isolated Flink indicator history and cannot mutate live
  strategy state.
- `BACKFILL`: persists historical facts without strategy evaluation.

The Backend tracks each strategy's last accepted LIVE event time, bar ID and
version under a row lock. Older LIVE bars are quarantined as stale jobs.
Non-LIVE market quality events cannot overwrite the live market state.

Submit jobs from inside the private network with
`flink run -py /opt/flink/usrlib/jobs/<job>.py`; no Flink or Kafka port is
published by Compose.
