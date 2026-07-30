# Phase 1 local paper-IBKR pipeline report

Date: 2026-07-30  
Branch: `main` (no branch was created)  
Workspace: `D:\Finflock\Trading Engine`

## Outcome

The local controlled-paper path now completes:

`strategy creation/selection -> activation preflight -> contract qualification -> market subscription -> historical warm-up -> Kafka -> Flink normalization/bar aggregation/indicators -> PostgreSQL -> first live evaluation -> StrategyTarget -> PortfolioTargetSnapshot -> rebalance -> sizing/risk -> OrderIntent/OMS -> BrokerCommand -> paper Gateway response/fill -> synchronized position`

The clean Docker Compose proof project is `finflock-phase1-proof-20260730a`. Its required services were intentionally left running for inspection. The project name was checked for existing volumes before launch, and Compose created new Kafka, PostgreSQL, and Flink volumes. Final execution readiness was:

```text
{'ready': True, 'status': 'READY', 'blockers': []}
```

Persisted proof from the clean run:

```text
strategy_id=1
state=LONG
warmup_evidence=1
warmup_bars=25
live_bars=3
indicators=84
execution_price_usable=True
runs=2
targets=1
target_snapshots=2
rebalances=2
intents=1
sizing=1
risk=1
orders_filled=1
commands_acknowledged=1
fills=1
positions=1
```

`ALLOW_LIVE_TRADING` remained false. Credentials and API keys remained environment-only and were not printed, logged, seeded, or committed. The test used the controlled paper Gateway response path permitted by the acceptance criteria; it did not open an external `ib_async` session to an installed IBKR paper Gateway.

## Implemented behavior

- Portfolio Builder construction remains a preview/allocation workflow and no longer creates strategy execution orders.
- Strategy lifecycle now distinguishes activation, subscription, warm-up, waiting for a live bar, first evaluation, and execution-active stages. Strategies without a valid target contribute HOLD/zero.
- The fixed 300-second activation/warm-up timeout no longer applies to `READY_WAITING_FOR_LIVE_BAR`; live-bar expiry is timeframe-aware.
- Paper execution pricing accepts only fresh, usable live `InstrumentMarketState` data. Finnhub historical closes remain preview/warm-up inputs only.
- Retryable target coordination errors remain queued with bounded exponential backoff.
- Activation preflight checks Kafka connectivity/topics, Flink jobs/checkpoints, outbox publishing, the backend consumer, workers, Gateway/account state, and reconciliation readiness.
- The market consumer commits successful events and deterministic invalid events recorded in the DLQ. Transient database/infrastructure failures do not commit. `python manage.py replay_market_dlq` requeues recorded events.
- Normalization now consistently uses the v2 consumer group/job name.
- Warm-up readiness stores bar IDs/timestamps, provider and provider generation, strategy version, and requirement hashes.
- Strategy-level timeout handling no longer marks a shared subscription failed unless the provider subscription itself fails.
- Provider recovery preserves and restores the pre-failure active trading state when the strategy already has audited warm-up and a completed first evaluation; strategies that were not ready still resume at warm-up.
- Paper Gateway synchronization supports the static local environment-configured session, account discovery, reconciliation, generation-aware cursor reset, controlled fill responses, and stable qualified contract identity.
- The PowerShell smoke test now fails whenever either preflight or final execution readiness is false.

## Changed files

Environment and Compose:

- `.env.example` — documents v2 groups and Phase 1 readiness/paper settings.
- `Backend/.env.example` — documents backend readiness and paper-Gateway settings.
- `Backend/config/settings.py` — loads the repository-root `.env`, adds Phase 1 settings, and enforces environment-sourced local paper configuration.
- `Backend/config/test_settings.py` — isolates unit-test preflight/ADV behavior.
- `docker-compose.yml` — corrects environment wiring and v2 groups, adds the controlled paper profile, and pins `ALLOW_LIVE_TRADING=false`.
- Repository-root `.env` (ignored, not committed) — only its outdated normalization group name was changed from v1 to v2; secret values were never displayed.

Lifecycle, readiness, warm-up, and market processing:

- `Backend/apps/strategies/models.py` — lifecycle stage timestamps and auditable warm-up readiness.
- `Backend/apps/strategies/framework.py` — activation preflight, lifecycle transitions, first-live evaluation, and execution-active transition.
- `Backend/apps/strategies/views.py` — exposes distinct activation/execution stages and readiness evidence.
- `Backend/apps/strategies/migrations/0012_strategy_runtime_stage_timestamps_and_warmup_audit.py` — schema for lifecycle timestamps and warm-up audit.
- `Backend/apps/market_streams/models.py` — bar provenance and execution-price usability.
- `Backend/apps/market_streams/services.py` — provenance persistence, complete warm-up selection/evidence, and first-live-bar handling.
- `Backend/apps/market_streams/subscriptions.py` — derives active indicator/ADV requirements.
- `Backend/apps/market_streams/tasks.py` — separates warm-up and timeframe-aware live-bar timeout handling.
- `Backend/apps/market_streams/migrations/0010_marketbar_provider_provenance.py` — market-bar provenance schema.
- `Backend/apps/market_data/fallback.py` — preserves/restores audited active strategy state across real provider failure and recovery.
- `streaming/flink/jobs/market_normalization.py` — normalization v2 job/group identity.
- `streaming/flink/jobs/bar_aggregation.py` — carries provenance through final bars.
- `streaming/flink/jobs/processing.py` — deterministic provenance/fingerprint processing.

Coordination, pricing, sizing, OMS, and dispatch:

- `Backend/apps/allocation/models.py` — retry scheduling fields for target coordination.
- `Backend/apps/allocation/migrations/0013_target_coordination_retry_queue.py` — coordination retry schema.
- `Backend/apps/rebalancing/coordinator.py` — HOLD/zero contribution semantics, retry/backoff, and safe PostgreSQL locking.
- `Backend/apps/rebalancing/services.py` — strict fresh-price execution inputs and no-op HOLD filtering.
- `Backend/apps/risk/pricing.py` — execution-usable market-state prices only.
- `Backend/apps/execution/dispatch.py` — qualified contract identity in broker commands.
- `Backend/apps/execution/readiness.py` — complete activation/execution infrastructure readiness.
- `Backend/apps/portfolio_construction/services.py` — separates preview allocation from strategy execution.

Kafka, outbox, and DLQ:

- `Backend/apps/event_bus/services.py` — deterministic/transient classification and DLQ replay service.
- `Backend/apps/event_bus/tasks.py` — publisher heartbeat, required-topic checks, and v2 group health.
- `Backend/apps/event_bus/management/__init__.py` — management package.
- `Backend/apps/event_bus/management/commands/__init__.py` — management command package.
- `Backend/apps/event_bus/management/commands/replay_market_dlq.py` — DLQ replay command.
- `Backend/apps/market_streams/management/commands/consume_market_streams.py` — correct offset commit semantics and v2 group.

Paper Gateway and broker synchronization:

- `Backend/apps/broker_gateway/client.py` — idempotent retries for safe Gateway POST operations.
- `Backend/apps/broker_gateway/models.py` — broker sync generation cursor.
- `Backend/apps/broker_gateway/services.py` — static local paper session/account synchronization and paper-only enforcement.
- `Backend/apps/broker_gateway/sync.py` — generation-aware event cursor reset.
- `Backend/apps/broker_gateway/tasks.py` — managed/static session synchronization.
- `Backend/apps/broker_gateway/management/commands/sync_local_paper_gateway.py` — explicit local paper sync command.
- `Backend/apps/broker_gateway/migrations/0004_brokersynccursor_connection_generation.py` — cursor generation schema.
- `IB_gateway/broker/ib_async_adapter.py` — explicit WARMUP/LIVE event provenance.
- `IB_gateway/broker/mock.py` — stable qualification, market heartbeat, paper account/events, controlled acknowledgement/fill, executions, and positions.
- `IB_gateway/config/settings.py` — persistent SQLite connection behavior for the local Gateway.
- `IB_gateway/gateway_service/apps.py` — WAL/busy-timeout initialization without startup lock races.
- `IB_gateway/gateway_service/views.py` — accepts qualified local symbol/primary exchange.

Frontend and operational status:

- `Frontend/src/api/types.ts` — distinct lifecycle/readiness stage types.
- `Frontend/src/features/portfolio-builder/PortfolioBuilderPage.tsx` — displays separated construction and execution stages.
- `docs/automatic_execution_smoke.ps1` — builds/starts the profile, waits for jobs/checkpoints/consumer, reconciles, checks readiness, and runs the real test.
- `Backend/apps/strategies/management/__init__.py` — management package.
- `Backend/apps/strategies/management/commands/__init__.py` — management command package.
- `Backend/apps/strategies/management/commands/retire_paper_smoke_strategies.py` — retires prior smoke strategies without creating orders.

Tests:

- `Backend/pytest.ini` — registers the real Docker integration marker.
- `Backend/tests/test_docker_paper_pipeline.py` — PostgreSQL/Kafka/Flink/paper-Gateway end-to-end proof.
- `Backend/tests/test_broker_sync.py` — generation-aware broker synchronization.
- `Backend/tests/test_event_bus.py` — consumer commit classification and DLQ replay.
- `Backend/tests/test_execution_readiness.py` — expanded readiness signals/blockers.
- `Backend/tests/test_gateway_client.py` — safe idempotent retry behavior.
- `Backend/tests/test_market_subscription_events.py` — provider generation/provenance behavior.
- `Backend/tests/test_finnhub_fallback.py` — provider failover plus audited active-state recovery.
- `Backend/tests/test_strategy_activation_lifecycle.py` — lifecycle and timeout behavior.
- `Backend/tests/test_target_coordination.py` — HOLD semantics, retries, and fresh prices.
- `IB_gateway/tests/test_api.py` — qualified contract fields and controlled paper API behavior.
- `docs/phase1_paper_pipeline_report.md` — this implementation and verification ledger.

Pre-existing untracked files under `IB_gateway/.pytest-tmp-gateway/` and `tmp/` were present before implementation and were left untouched.

## Commands and results

Repository and implementation inspection used read-only `git branch --show-current`, `git status --short --untracked-files=all`, `git diff --stat`, `git diff --name-only`, `rg`, `rg --files`, and `Get-Content` queries across the repository, Compose file, settings, models, migrations, services, tasks, tests, frontend types, Gateway, and Flink jobs. Branch inspection returned `main`.

Static/configuration checks:

```powershell
docker compose --profile paper-ibkr config --quiet
python -m compileall -q Backend IB_gateway streaming
docker compose run --rm -e USE_SQLITE=true backend python manage.py makemigrations --check --dry-run
git diff --check
npm run build
```

Results:

- Compose configuration: passed.
- Python compilation: passed; only inaccessible cache-directory notices were emitted.
- Migration drift: `No changes detected`.
- Diff whitespace check: passed; Git emitted only the repository's CRLF conversion warnings.
- Frontend TypeScript/Vite build: passed. Vite retained the existing warning that `runtime-config.js` is not a module script.
- A repository search found no remaining outdated normalization-v1 consumer-group name.
- PowerShell parser validation for `docs/automatic_execution_smoke.ps1`: passed.
- Root environment verification reported only booleans: `FINNHUB_API_KEY` loaded, `ALLOW_LIVE_TRADING=false`, PostgreSQL selected.

Final exact affected-backend regression command (isolated with `docker run`, so it could not add a duplicate service alias to the live proof network):

```powershell
docker run --rm --entrypoint pytest -v "D:\Finflock\Trading Engine\Backend:/app" -v "D:\Finflock\Trading Engine\streaming:/workspace/streaming" -e PYTHONPATH=/app:/workspace -w /app finflock-phase1-proof-20260730a-backend tests/test_broker_command_dispatch.py tests/test_broker_sync.py tests/test_event_bus.py tests/test_execution_readiness.py tests/test_finnhub_fallback.py tests/test_gateway_client.py tests/test_market_subscription_events.py tests/test_oms_risk.py tests/test_portfolio_construction.py tests/test_rebalancing_workflows.py tests/test_strategy_activation_lifecycle.py tests/test_strategy_evaluation_jobs.py tests/test_target_coordination.py -m "not docker_integration" -q
```

Result: `184 passed, 1 skipped in 35.85s`. Earlier affected-backend runs passed `158` and `166` tests before the provider-recovery regression was added.

Final Gateway command:

```powershell
docker run --rm --entrypoint pytest -v "D:\Finflock\Trading Engine\IB_gateway:/app" -e MOCK_BROKER_ACCOUNT_ID= -e MOCK_BROKER_AUTO_FILL=false -w /app finflock-phase1-proof-20260730a-paper-ibkr-gateway -q
```

Result: `115 passed in 2.48s`.

Final Flink processing commands:

```powershell
docker run --rm --entrypoint pytest -v "D:\Finflock\Trading Engine\streaming:/workspace/streaming" -e PYTHONPATH=/workspace -w /workspace finflock-phase1-proof-20260730a-backend streaming/flink/tests/test_processing.py -q
docker run --rm --entrypoint pytest -v "D:\Finflock\Trading Engine\Backend:/app" -v "D:\Finflock\Trading Engine\streaming:/workspace/streaming" -e PYTHONPATH=/app:/workspace -w /app finflock-phase1-proof-20260730a-backend tests/test_streaming_determinism.py -q
```

Results: `11 passed in 0.44s` and `5 passed in 26.65s`.

Clean build/start/migration/pipeline commands:

```powershell
docker volume ls --filter name=finflock-phase1-proof-20260730a --format "{{.Name}}"
powershell -NoProfile -ExecutionPolicy Bypass -File .\docs\automatic_execution_smoke.ps1 -ComposeProjectName finflock-phase1-proof-20260730a -TimeoutSeconds 300
docker compose -p finflock-phase1-proof-20260730a --profile paper-ibkr exec -T backend python manage.py migrate --noinput
docker compose -p finflock-phase1-proof-20260730a --profile paper-ibkr ps
```

Results:

- Smoke stages passed: service health, Flink jobs, recent checkpoints, backend consumer, paper-Gateway reconciliation, prior-strategy retirement, execution readiness, architecture contract, paper pipeline, and final execution readiness.
- The pre-launch volume query returned no rows, and the smoke output showed new Kafka, PostgreSQL, checkpoint, and savepoint volumes being created.
- Real integration test: `1 passed in 27.52s`.
- Explicit migrations: `No migrations to apply`.
- Final readiness: `READY`, no blockers.
- Nine delayed observations over 45 seconds all returned `(True, LONG)`, remaining healthy beyond the configured provider failover grace.
- Backend, PostgreSQL, Kafka, Redis, both Flink services, and the paper Gateway were running; services with configured health checks were healthy.

Read-only Django shell commands were also run inside the verified backend to print the final readiness dictionary and the aggregate proof counts shown at the start of this report. They deliberately printed no secrets.

During iterative verification, isolated runs exposed and led to fixes for Kafka startup timing, Docker test-file availability, PostgreSQL nullable outer-join locks, qualified identity propagation, broker status expectations, mock identifier/generation uniqueness, warm-up selection over incomplete newest bars, target price prerequisites, a transient Gateway SQLite lock, and provider-recovery lifecycle state. Two final test-command setup mistakes were non-code failures: the production image omits `config.test_settings`, and an ephemeral Compose run initially used the service entrypoint instead of `pytest`; both were corrected with mounted source and `--entrypoint pytest`. A Flink collection attempt with `PYTHONPATH=/streaming` failed import collection and was corrected to `PYTHONPATH=/workspace`.

One smoke attempt used the pre-existing `finflock-phase1-final` volume namespace. It retired two old strategies and correctly produced no new intent because prior reconciled state already satisfied the target; the test timed out with `state=LONG`, a valid target, and no new intent. That project was stopped without `-v`. The final proof used the volume-checked `finflock-phase1-proof-20260730a` namespace, retired zero strategies, and passed.

No Docker volume was deleted. Temporary/failed isolated Compose projects were stopped with `docker compose ... down` without `-v`; one exact ephemeral supervisor container was stopped with `docker stop finflock-phase1-delivery-backend-run-dd98b269b085`.

## Remaining blockers and scope notes

There is no blocker for the requested clean local controlled-paper pipeline.

- The external installed-IBKR `ib_async` adapter path was not exercised because the acceptance criterion permits a controlled paper broker response. Set `LOCAL_PAPER_GATEWAY_ADAPTER=ib_async` and provide local paper credentials through environment variables or the existing credential-entry flow to test that external session; never enable live trading.
- Reusing a stateful database after retiring a strategy that still owns a reconciled position correctly requires a fresh usable market subscription/price for that holding. The reproduction below uses a fresh Compose project to avoid mixing prior test state.

## Exact reproduction

The verified services currently occupy the local ports. From `D:\Finflock\Trading Engine`, stop that project without deleting its volumes, then run the smoke script with a fresh project name:

```powershell
docker compose -p finflock-phase1-proof-20260730a --profile paper-ibkr down
powershell -NoProfile -ExecutionPolicy Bypass -File .\docs\automatic_execution_smoke.ps1 -ComposeProjectName finflock-phase1-repro -TimeoutSeconds 300
```

The second command is the complete clean proof. It builds and starts the required Docker services, applies migrations, waits for Kafka/Flink/checkpoints/consumer/Gateway/reconciliation readiness, fails on false execution readiness, and runs the PostgreSQL/Kafka/Flink/paper-Gateway integration test.
