# Runtime diagnosis

Diagnosed on 2026-07-13 against the application stack and a separately validated
authenticated IBKR paper child. This document records the pre-fix evidence.

## Baseline

- Backend: `53 passed in 8.05s`.
- Gateway: `11 passed in 0.32s`.
- Frontend: `11 passed` across 3 files.
- Flink calculation tests: `3 passed in 0.07s`.
- `docker compose config --quiet` passed.
- The application/infrastructure stack started successfully, and the separately
  validated broker child reported `connected=true`, `reconciled=true`, and
  `mode=paper`. All five expected Flink jobs reported `RUNNING` with no failed tasks.

The green unit and container-health results do not exercise the broker-to-Kafka
market-data path.

## 1. Instrument search and exact contract selection

### Observed issue

The strategy builder accepts a ticker and exchange, but an operator cannot search
IBKR by ticker/company name, compare ambiguous matches, or select an exact contract.

### Evidence

- `GET /api/v1/instruments/search/?query=AMD` returned HTTP 404.
- The Frontend uses a ticker input backed by a datalist of local instruments and
  calls only `POST /api/v1/instruments/resolve/`.
- The Gateway exposes `POST /contracts/qualify/` but no search endpoint.
- The real IBKR adapter constructs a generic `Stock(symbol, exchange, currency)`
  and calls `qualifyContracts`. It takes the first qualified contract and returns
  only conId, symbol, exchange, currency, and `qualified`.
- A non-seeded AMD request proved that basic real qualification works: the Backend
  created instrument 5, queued Gateway command 1, and persisted conId 4391 after
  the command completed. The stored `primary_exchange` and `local_symbol` remained
  empty/default because those fields were not returned by the adapter.

### Confirmed root cause

There is no broker-backed matching-symbol/contract-details operation in the
Gateway or Backend. The current qualification operation cannot present ambiguity
and discards the broker fields needed to identify the exact contract. The
Frontend therefore has no exact contract result to select.

### Affected components

Gateway broker adapter and API, Backend Gateway client/instrument API and contract
persistence, Frontend strategy builder.

### Proposed fix

Add Gateway matching-symbol and contract-detail search, return full contract
identity, require selection of a conId for ambiguous results, qualify that exact
contract, and persist all broker identity fields. Add a debounced Frontend search
and explicit result selection.

## 2. Missing market stream and failed strategy-input publication

### Observed issue

Enabled strategies register database input bindings, but neither their registry
events nor broker market data enter Kafka.

### Evidence

- The diagnostic AMD fixed-weight strategy (instance 30) was created in SHADOW
  mode, enabled successfully, and had one active BAR/OHLCV input binding with an
  active reference count of 1.
- After 12 seconds it was still `WARMING_UP`, with progress `0/1` and no final bar.
- Kafka end offsets were 0 for every partition of `strategy.inputs.v1`,
  `market.raw.v1`, `market.canonical.v1`, `market.bars.v1`,
  `market.indicators.v1`, and `dead-letter.v1`.
- PostgreSQL contained 0 market bars, 0 final bars, 0 indicators, and 0 instrument
  market-state rows.
- The Backend market consumer was running and subscribed to the three Flink output
  topics. All five Flink jobs were `RUNNING`.
- Every Backend outbox row was `FAILED` (156 rows at capture time). Both input
  events for instance 30 had failed five attempts with:

  ```text
  [Errno 2] No such file or directory:
  '/streaming/kafka/schemas/event-envelope-v1.json'
  ```

- `Backend/apps/event_bus/schemas.py` resolves schemas outside the Backend build
  context, while the Backend Dockerfile copies only `Backend/` into `/app`.
- No Gateway adapter method or command requests historical bars, subscribes to
  live bars/ticks, cancels market data, or publishes `market.raw.v1`.

### Confirmed root cause

The active-input control plane is broken in the Backend container because the
event schema files are absent, so outbox events cannot be validated or published.
Independently, the market-data producer does not exist: enabling a strategy never
creates a durable subscription or tells the Gateway to request historical/live
data. Running consumers and Flink jobs consequently have no input.

### Affected components

Backend Docker packaging and outbox publisher, strategy enable/pause lifecycle,
Gateway command model/API/worker/broker adapter, Kafka raw-market producer.

### Proposed fix

Package event schemas inside the Backend image, add a durable reference-counted
subscription model, enqueue idempotent subscribe/cancel commands on strategy
lifecycle changes, restore active subscriptions after restart, request historical
and live bars in the sole Gateway broker worker, and publish canonical raw events
to Kafka with stored broker errors and timestamps.

## 3. Static symbol map blocks newly qualified instruments

### Observed issue

A newly qualified conId is not registered with the market normalizer.

### Evidence

- Compose passes `INSTRUMENT_SYMBOL_MAP`, defaulting to `{}`, only to the Flink
  JobManager.
- `market_normalization.py` reads that environment value once at job construction.
- `normalize_market_event` resolves only `symbol_map[raw["symbol"]]`; an unknown
  symbol raises an error and is routed to the dead-letter output.
- No instrument-registry topic or runtime registry update is produced when AMD
  conId 4391 is persisted.

### Confirmed root cause

Normalization uses a process-start environment snapshot rather than broker conId
or a dynamic instrument registry. New contracts cannot become recognizable
without changing configuration and restarting Flink.

### Affected components

Backend instrument persistence/outbox, Kafka topic definitions, Flink market
normalization, runtime health reporting.

### Proposed fix

Publish durable instrument-registry events when contracts are qualified, consume
them as Flink broadcast state, resolve market events primarily by conId/canonical
instrument ID, restore the registry from compacted Kafka state after restart, and
surface unknown mappings as explicit subscription/strategy errors.

## 4. Endless strategy warm-up

### Observed issue

Enabled strategies remain in `WARMING_UP` indefinitely with no visible reason.

### Evidence

- Existing enabled instances 28 and 29 had remained `WARMING_UP` at `0/N` since
  04:07 UTC and 06:04 UTC respectively. The newly enabled instance 30 reproduced
  the same behavior at `0/1`.
- Their input bindings were active, but the market tables and Kafka market topics
  were empty for the reasons above.
- Warm-up progress is updated only inside `evaluate_instance`, after a final bar
  and every indicator for that exact bar are already ready. Persisting usable
  final bars does not independently update per-strategy progress.
- There is no scheduled warm-up watchdog, last-progress timestamp, timeout state,
  or diagnosis that distinguishes no subscription, no raw events, stopped Flink,
  missing mapping, permission failure, or stopped Backend consumption.

### Confirmed root cause

The missing control/data-plane producers prevent all progress. In addition, the
warm-up state machine is evaluation-driven instead of final-bar-driven and has no
timeout/error transition, so a broken upstream path is represented forever as a
normal warm-up.

### Affected components

Strategy lifecycle and model, market persistence/evaluation, scheduled health
tasks, strategy APIs, Frontend readiness/status views.

### Proposed fix

Load enough historical bars (including a safety margin), pass historical and live
bars through the same deduplicated path, calculate each strategy's usable final
bars against its own requirements, update progress as final bars/indicators
arrive, evaluate once all exact inputs are ready, and transition stalled warm-up
to `BLOCKED` with a precise stored reason.

## 5. Missing IBKR cancellation/rejection reasons

### Observed issue

IBKR-cancelled orders show a final state but no broker explanation or status
timeline in the UI.

### Evidence

- Four persisted orders were `CANCELLED`. Their Backend status-history rows all
  used `source="broker_sync"` and the hardcoded reason `IBKR order status`.
- The Gateway `_trade_data` snapshot includes status and quantities only. It does
  not serialize `whyHeld`, warning text, advanced rejection JSON, error code,
  broker message, or IBKR trade-log entries.
- The Gateway worker publishes periodic aggregate snapshots and command completion
  events; it does not register durable error/order-status callbacks with their
  broker diagnostics.
- `OrderStatusHistory` stores only from/to status, source, one reason string, and
  event key. It cannot store reason code, structured details, occurrence time, or
  whether an operator requested cancellation.
- The order list API returns no status history or diagnostics, there is no order
  detail endpoint, and the Frontend orders page has no broker timeline drawer.

### Confirmed root cause

Broker diagnostic fields are discarded at the Gateway boundary, and the Backend
history schema/API cannot represent them. Snapshot sync then substitutes a generic
reason, making operator cancellation and IBKR cancellation/rejection
indistinguishable.

### Affected components

Gateway IBKR callbacks/snapshots and durable event buffer, Backend broker sync/OMS
history/API, Frontend order activity view.

### Proposed fix

Capture IBKR error, status, `whyHeld`, warning, advanced reject JSON, and trade-log
callbacks as durable events; extend append-only history with structured broker
diagnostics and operator-requested attribution; add an order detail API; and show
the exact chronological history in a Frontend order drawer. When IBKR supplied no
reason, display `No broker reason received`.

## 6. Health reports green while the strategy path is broken

### Observed issue

The visible system state can be green even when no strategy data can flow.

### Evidence

- Gateway health was connected/reconciled, Kafka connectivity health was healthy,
  and every Flink job was running while the input outbox was entirely failed and
  all market topics/tables were empty.
- Current health checks test process/connectivity state, not per-strategy event
  freshness or outbox/subscription progress.

### Confirmed root cause

Health is component-oriented and does not aggregate the end-to-end strategy data
path.

### Affected components

Backend streaming health API/tasks, strategy detail API, Frontend global and
strategy health badges.

### Proposed fix

Expose per-subscription timestamps/errors and per-strategy raw/canonical/final
bar/indicator/run progress, plus outbox failures, consumer state, Flink state,
dead-letter count, and stale registry entries. Derive the global badge from this
path rather than HTTP/process liveness alone.

## Safety constraints retained for implementation

- The Gateway remains the only TWS socket owner.
- Diagnostic strategy 30 uses SHADOW mode and cannot place an order.
- The connected broker session is paper mode.
- No change may bypass idempotency, sizing, risk, OMS, ledger, reconciliation, or
  paper-first gates.
- Configurable strategies reject LIVE mode, and the backend rejects a live-trading environment request at startup.

## Post-fix runtime verification

Verified on 2026-07-13 after the phase-by-phase implementation, an application
stack rebuild, and separate child-image validation.

### Confirmed repaired paths

- Real IBKR search for `SHOP` returned 21 distinct contracts. Exact selection of
  conId `195014116` resolved and persisted the NASDAQ/USD stock contract instead
  of guessing from the ticker.
- The qualified contract published to the compacted `instrument.registry.v1`
  topic. The registry end offset advanced from 4 to 5 before the strategy was
  enabled, and Flink resolved subsequent raw events by conId.
- Enabling SHADOW strategy instance 31 created a durable, reference-counted
  subscription. Real IBKR historical data traversed Gateway, Kafka, Flink, and
  Backend persistence: 20 final SHOP 5-minute bars and 20 RSI values were stored.
- Warm-up advanced from real final bars and indicators to `15/15`. The latest RSI
  was `50.0000000000`; the strategy did not evaluate or place an order because the
  live subscription was unavailable.
- IBKR returned exact API market-data error 10089:

  ```text
  Requested market data requires additional subscription for API. See link in
  'Market Data Connections' dialog for more details.
  ```

  The subscription, strategy detail, block reason, and streaming-health payload
  retained that reason. AAPL also returned exact error 354, and other attempted
  contracts returned error 420, proving broker errors no longer disappear behind
  an endless warm-up.
- Pausing the two diagnostic strategies reduced their input reference counts to
  zero. A routing-default defect found during this cleanup was fixed; the durable
  cancel command then completed and the SHOP subscription became `INACTIVE` with
  an empty error field.
- The Backend outbox recovered all 156 baseline schema-package failures. At final
  verification it contained 302 published events, zero pending events, and zero
  failed events. Backend consumer topic lag was zero.
- The Gateway was restarted and returned with a new connection generation,
  `connected=true`, `reconciled=true`, and `mode=paper`. Active subscriptions were
  reissued for the new generation while diagnostic errors remained visible.
- Backend and both Flink containers were restarted after the SHOP events. Counts
  remained 20 final bars, 20 indicators, and 40 consumed events, with no duplicate
  rows. All five Flink jobs returned to `RUNNING` with all tasks running.
- Final HTTP smoke returned 200 for Backend health, instruments, strategy detail,
  orders, and streaming health; Frontend root and health; and separate child health.
- The historical broker child exposed only HTTP target port 8080, not raw TWS
  paper port 4002. The default execution mode is
  `SHADOW`.

### Final automated results

- Backend: `66 passed in 8.52s`; Django system check passed; no missing migrations.
- Gateway: `18 passed in 0.26s`; Django system check passed.
- Frontend: `12 passed in 7.28s`; TypeScript/Vite production build passed
  (`478.15 kB` JavaScript bundle, `147.14 kB` gzip).
- Flink calculation tests: `3 passed in 0.02s`; Python bytecode compilation passed.
- `docker compose config --quiet` and a full `docker compose build` passed.
- All application/infrastructure services were up; health-enabled services were healthy;
  all five Flink jobs were `RUNNING` with all tasks running.

### Verification boundary and remaining paper-account checks

The complete real live-bar-to-strategy-run path was **not** exercised. The paper
account currently lacks the IBKR API market-data subscription needed for live
SHOP/AAPL/MSFT/AMD data. Historical final bars and indicators completed, but the
strategy correctly blocked before evaluation on the exact broker error, so there
were zero SHOP strategy runs and zero orders.

After enabling the required paper-account market-data entitlement (or confirmed
API delayed-data access), repeat the test during an applicable market session and
verify a live final bar, indicator, strategy run, and SHADOW target in order. A
real paper order should also be deliberately cancelled or rejected to confirm a
new IBKR callback populates reason code, message, structured diagnostics, and the
Frontend order timeline. Existing historical cancelled orders predate this change
and still contain the former generic `IBKR order status` row; they were not
rewritten because order history is append-only.

The Frontend behavior is covered by unit tests, production build, API/detail
smoke, and Nginx HTTP smoke. An in-app interactive browser walkthrough could not
be run because this session did not expose the browser-use skill's required Node
runtime; no alternate browser driver was substituted.
