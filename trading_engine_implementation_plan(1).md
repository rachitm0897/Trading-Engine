# Trading Engine Backend Implementation Plan

## 1. Scope

This phase focuses on:

- Backend correctness and paper-trading safety.
- Broker, order, strategy, allocation, reconciliation, and rebalance reliability.
- Removal of unused, duplicate, and legacy code.
- Database, CPU, memory, and network efficiency.
- Automated tests and runtime verification.
- Preserving existing frontend behaviour where practical.

This phase does **not** include:

- User authentication or authorization.
- User-specific or tenant-specific workflows.
- Splitting the system into separate deployment services.
- Live trading enablement.
- Major frontend redesigns.

All broker execution must remain paper-only.

---

## 2. Working Rules

1. Read this plan completely before changing code.
2. Inspect the actual repository before deciding how to implement each item.
3. Work phase by phase in the order listed below.
4. Make small, reviewable changes.
5. Add or update tests with every behavioural change.
6. Do not keep unused code as `legacy`, `deprecated`, `compatibility`, or `v1`.
7. Delete unused code only after its dependencies have been migrated and tests pass.
8. Do not hide failures by weakening tests, swallowing exceptions, or using fake migrations.
9. Preserve existing API contracts unless a correctness or safety fix requires a documented change.
10. Record assumptions and unresolved limitations in the final audit document.

---

## 3. Phase 1: Establish a Verified Baseline

Before changing behaviour:

1. Run the backend, gateway, and frontend tests.
2. Run Django system and migration checks.
3. Start the Docker Compose stack.
4. Verify the available components:
   - PostgreSQL
   - Redis
   - Kafka
   - Flink
   - Django backend
   - Celery worker
   - Celery Beat
   - Market-stream consumer
   - IBKR Gateway or mock broker
5. Record all existing failures in `docs/audit-baseline.md`.

Do not modify tests merely to create an artificial green baseline.

### Completion Criteria

- Existing failures are documented.
- The migration state is understood.
- The local stack starts successfully, or exact startup failures are documented.
- Important execution paths are identified before refactoring begins.

---

## 4. Phase 2: Fix Broker Position and Reconciliation Correctness

### 4.1 Broker Position Synchronization

Fix position synchronization so a broker snapshot affects only the correct broker account.

Requirements:

- Group incoming positions by broker account.
- Update only portfolios associated with the relevant broker account.
- Never reset positions belonging to unrelated accounts or portfolios.
- Set missing positions to zero only after receiving a confirmed complete snapshot.
- Treat incomplete or failed snapshots as non-authoritative.
- Process each complete account snapshot atomically.
- Preserve snapshot and reconciliation audit information.

Add tests for:

- Two accounts holding the same instrument.
- One account updating without modifying another account.
- Empty complete snapshots.
- Partial snapshots.
- Duplicate snapshots.
- Snapshot processing failure midway.

### 4.2 Account-Scoped Reconciliation

Reconciliation must compare records using:

```text
broker_account_id + contract_id
```

Requirements:

- Each reconciliation run must identify the broker account being checked.
- Do not aggregate positions from different accounts.
- Update reconciliation status only for the relevant account.
- Resolve old breaks only when the relevant account is successfully reconciled.
- Preserve unresolved breaks for other accounts.

Add tests for:

- The same contract held by multiple accounts.
- One reconciled account and one unreconciled account.
- Missing executions in one account.
- Account-specific break creation and resolution.

### 4.3 Position Accounting

When fills are applied:

- Update position quantity correctly.
- Update weighted-average cost correctly.
- Handle partial fills.
- Handle position increases and reductions.
- Handle complete position closure.
- Record realized profit and loss where supported.
- Prevent duplicate execution callbacks from changing state twice.
- Keep order, execution, and position updates transactionally consistent.

Document the accounting method used.

---

## 5. Phase 3: Fix Order and Broker-Command Reliability

### 5.1 Strong Idempotency

Use canonical request hashes for important operations:

- Gateway commands.
- Manual orders.
- Strategy-generated order intents.
- Deposits and withdrawals.
- Rebalances.
- Portfolio optimizations.
- Strategy actions.

Required behaviour:

- Same key and same request: return the existing operation.
- Same key and different request: return a conflict error.
- Completed operation: never execute again.
- In-progress operation: return its current state.
- Failed retryable operation: allow an explicit controlled retry.
- Non-retryable failure: return the stored failure clearly.

### 5.2 Gateway Command Leasing and Recovery

Use a command lifecycle such as:

```text
PENDING
PROCESSING
COMPLETED
FAILED
UNKNOWN
```

Store:

- `request_hash`
- `claimed_by`
- `claimed_at`
- `lease_expires_at`
- `attempt_count`
- `completed_at`
- `last_error`

The worker must:

1. Claim commands atomically.
2. Prevent multiple workers from owning the same active command.
3. Recover expired `PROCESSING` commands after a crash.
4. Check broker references before resubmitting uncertain order commands.
5. Avoid duplicate IBKR orders.
6. Preserve the result of every attempt.

Add crash-recovery tests for:

- Order placement.
- Order modification.
- Order cancellation.
- Worker failure before broker submission.
- Worker failure after broker submission but before database completion.

### 5.3 External Calls and Transactions

Do not keep database transactions open while waiting for:

- IBKR Gateway.
- Finnhub.
- Kafka.
- Other external systems.

Persist an internal command or job first, commit it, and then process the external action safely.

HTTP endpoints may return an accepted or queued state rather than waiting for completion.

---

## 6. Phase 4: Fix Rebalance, Allocation, and Risk Logic

### 6.1 Sell-Before-Buy Rebalancing

A rebalance must not unlock buy orders only because all sell orders are terminal.

Buy execution may proceed only when:

- The configured sell-fill threshold is reached; or
- The plan is recalculated using actual fills and confirmed available capital.

Rejected, cancelled, or expired sell orders below the threshold must place the rebalance in a blocked, failed, or partially completed state.

Add tests for:

- Fully filled sells.
- Partial fills above the threshold.
- Partial fills below the threshold.
- Rejected sells.
- Cancelled sells.
- Mixed filled and rejected sells.
- Restart and recovery during rebalancing.

### 6.2 Retryable Flows

A failed flow, optimization, or rebalance must not permanently poison its idempotency key.

Requirements:

- Preserve complete attempt history.
- Distinguish retryable from non-retryable failures.
- Allow explicit retries without creating duplicate successful operations.
- Never silently rerun a completed operation.

### 6.3 Scoped Kill Switches

Respect existing kill-switch scopes:

```text
GLOBAL
ACCOUNT
PORTFOLIO
STRATEGY
INSTRUMENT
```

Only switches matching the current order intent should block it.

Add isolated tests for every scope and combinations of scopes.

### 6.4 Capital Reservation

Risk checks must account for:

- Existing open buy orders.
- Pending approved order intents.
- Estimated commissions and fees.
- Pending withdrawals.
- Other concurrent operations using the same capital.

Use row locking or an explicit capital-reservation model so concurrent requests cannot spend the same available cash.

Risk limits must come from persisted server-side policy, not from values supplied by an order request.

---

## 7. Phase 5: Simplify the Strategy Architecture

`StrategyInstance` must become the only active strategy runtime model.

### Migration Sequence

1. Identify every dependency on the old `TradingStrategy` model.
2. Add direct `StrategyInstance` references where required.
3. Backfill existing records.
4. Update:
   - Allocations
   - Strategy runs
   - Order intents
   - Charts
   - Execution timelines
   - Rebalancing
   - Position attribution
5. Stop creating both old and new strategy records.
6. Remove compatibility synchronization.
7. Remove old strategy endpoints and execution paths.
8. Remove the old strategy engine.
9. Remove the old model only after migration and tests succeed.

Delete unused wrappers, adapters, aliases, and forwarding functions that provide no meaningful abstraction.

Do not preserve removed code under another legacy name.

---

## 8. Phase 6: Replace Runtime Schema Adoption

The application must not repair or fake migration history during normal startup.

Use standard Django migrations:

```bash
python manage.py migrate --noinput
```

Steps:

1. Confirm the schema expected by the current models.
2. Create normal migrations for required changes.
3. Add a documented one-time procedure for upgrading an existing database.
4. Verify migration from a fresh database.
5. Verify migration from a copy of the current schema.
6. Remove the runtime schema-adoption command.
7. Remove `--fake-initial` and migration-table manipulation from normal startup.

---

## 9. Phase 7: Reduce Database and Server Resource Usage

### 9.1 Remove N+1 Queries

Optimize strategy, order, portfolio, allocation, and rebalance APIs using:

- `select_related`
- `prefetch_related`
- annotations
- subqueries
- lightweight list serializers

Add query-count tests for important list and detail endpoints.

### 9.2 Reduce Repeated Strategy Evaluation

A strategy should be evaluated once when all required inputs for a finalized bar are available.

Do not independently trigger readiness evaluation after:

- Bar persistence.
- Every individual indicator persistence.
- Duplicate market events.

Use an idempotent readiness key based on values such as:

```text
strategy_version + bar_id + bar_version
```

### 9.3 Optimize Warm-Up Checks

Do not count complete historical datasets for every event.

Use:

- Incremental readiness state.
- Limited queries.
- Cached progress.
- Existing finalized-bar counts maintained during ingestion.

### 9.4 Batch Kafka Outbox Publishing

Publish selected outbox messages as a batch and flush once per batch.

Requirements:

- Preserve per-event delivery status.
- Preserve retry behaviour.
- Do not mark events published before confirmation.
- Avoid flushing Kafka once per event.

### 9.5 Bulk Market-Data Writes

Replace row-by-row `update_or_create` loops with safe bulk inserts or bulk upserts.

Preserve uniqueness and correction behaviour for historical bars.

### 9.6 Database Indexes

Add indexes based on real query patterns for:

- Orders and order intents.
- Broker IDs and statuses.
- Gateway commands and events.
- Market bars and indicators.
- Strategy instances and runs.
- Rebalance runs and orders.
- Reconciliation breaks.
- Outbox events.
- Portfolio positions and allocations.

Use query plans, query counts, or timing measurements to justify important indexes.

### 9.7 Retention and Compaction

Add safe retention policies for:

- Acknowledged gateway events.
- Old health snapshots.
- Completed outbox events.
- Old stream-health records.
- Redundant broker snapshots.

Do not delete immutable order, execution, fill, accounting, or audit facts without an explicit documented rule.

---

## 10. Phase 8: Move Expensive Work Out of HTTP Requests

Use the existing Celery setup for:

- Portfolio optimization.
- Large historical market-data refreshes.
- Reconciliation.
- Kafka replay.
- Large rebalance calculations.
- Other long-running external-data operations.

HTTP endpoints should:

1. Validate the request.
2. Create a run or job record.
3. Queue the task.
4. Return the run identifier and status.

Do not run SciPy optimization or multiple external market-data requests directly inside Gunicorn request workers.

---

## 11. Phase 9: Improve Validation and Error Handling

Add strict validation for:

- Supported HTTP methods.
- Required fields.
- Decimal precision.
- Positive quantities.
- Order-type-specific price requirements.
- Account, portfolio, strategy, and instrument relationships.
- Idempotency keys.
- Gateway command payloads.
- State transitions.

Requirements:

- Reject invalid transitions explicitly.
- Do not catch broad exceptions without preserving error context.
- Strategy-processing failures must remain visible and retryable.
- Kafka consumer failures must not be silently treated as successful processing.
- Dead-letter behaviour must retain enough data for diagnosis and replay.

---

## 12. Phase 10: Testing and Verification

Run at minimum:

```bash
python manage.py check
python manage.py makemigrations --check
python manage.py migrate
pytest
```

Also run:

- Gateway tests.
- Celery task tests.
- Frontend tests.
- Frontend production build.
- Docker Compose startup verification.

Add integration and concurrency tests for:

- Complete order lifecycle.
- Duplicate requests and events.
- Gateway command recovery.
- Position synchronization.
- Position accounting.
- Account-scoped reconciliation.
- Strategy evaluation.
- Allocations and flows.
- Sell-before-buy rebalancing.
- Portfolio optimization.
- Kafka outbox publishing.
- Transaction rollback.
- Capital reservation.
- Concurrent order requests.

---

## 13. Required Documentation

Create `docs/backend-audit-results.md` containing:

- Baseline failures.
- Bugs fixed.
- Behavioural changes.
- Code and files deleted.
- Database migrations added.
- Performance improvements.
- Query-count or timing comparisons where available.
- Test commands executed.
- Exact test results.
- Remaining limitations.
- Deferred items.

Document any necessary API compatibility change before finalizing it.

---

## 14. Final Acceptance Conditions

The implementation is complete only when:

- A broker snapshot cannot overwrite unrelated portfolios.
- Reconciliation is broker-account-specific.
- Duplicate requests cannot create duplicate broker orders.
- Expired gateway commands can recover safely.
- Failed or cancelled sells cannot incorrectly fund buy orders.
- Position quantity and average cost are correct after fills.
- Duplicate fills have no repeated accounting effect.
- Kill switches respect their configured scope.
- Concurrent orders cannot spend the same capital.
- Failed idempotent operations can be retried safely.
- Expensive optimization and history work no longer block HTTP workers.
- The old strategy implementation is completely removed.
- Runtime schema adoption is completely removed.
- Important API query counts are bounded and tested.
- Migration checks pass.
- Backend and gateway tests pass.
- Frontend tests and production build pass.
- Remaining failures or limitations are explicitly documented.
