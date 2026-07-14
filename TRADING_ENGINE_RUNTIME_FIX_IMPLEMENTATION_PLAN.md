# Trading Engine Runtime Fix Implementation Plan

## 1. Objective

Repair the actual trading workflow, not only the frontend.

The system must support:

1. Searching and selecting any IBKR-supported instrument.
2. Qualifying and storing the exact broker contract.
3. Starting market-data subscriptions for active strategies.
4. Loading enough historical data to complete strategy warm-up.
5. Processing live data through Kafka, Flink, PostgreSQL, and strategy evaluation.
6. Showing exact IBKR cancellation and rejection reasons.
7. Exposing clear runtime health and failure information in the frontend.

---

## 2. Current Problems

### 2.1 Instrument selection

The frontend mainly suggests instruments already present in the local database.

Required behavior:

- Search IBKR by ticker or company name.
- Return multiple matching contracts.
- Show symbol, exchange, primary exchange, currency, asset type, local symbol, and conId.
- Let the user select the exact contract.
- Qualify and persist the selected contract.
- Make the new instrument immediately usable by strategies and streaming.

### 2.2 Strategy warm-up never completes

A strategy remains in `WARMING_UP` because the complete market-data path may not be running.

The complete path to verify is:

```text
Strategy enabled
    ↓
Input requirements registered
    ↓
IBKR historical data requested
    ↓
IBKR live market subscription created
    ↓
market.raw.v1
    ↓
Flink normalization
    ↓
Final bars
    ↓
Indicators
    ↓
Backend persistence
    ↓
Strategy evaluation
```

The current system must be checked for missing producers, broken subscriptions, static symbol mappings, stopped consumers, topic errors, and market-data permission failures.

### 2.3 IBKR order reason is missing

When IBKR cancels or rejects an order, only the final status is visible.

Required behavior:

- Capture IBKR error code.
- Capture broker message.
- Capture `whyHeld`.
- Capture advanced rejection details when available.
- Store the exact status transition.
- Distinguish operator cancellation from broker cancellation.
- Show the full order-status timeline in the frontend.

---

## 3. Phase 1: Runtime Diagnosis

Before modifying production code:

1. Run all current tests.
2. Start the complete Docker stack.
3. Inspect:
   - Backend logs
   - Gateway logs
   - Kafka logs
   - Flink JobManager logs
   - Flink TaskManager logs
4. Check Docker service health.
5. Check Kafka topic offsets.
6. Check Flink job states.
7. Check database rows for:
   - strategy input bindings;
   - market bars;
   - indicators;
   - dead-letter events;
   - outbox events;
   - order status history.
8. Test instrument qualification with a ticker not already stored.
9. Create a strategy and trace where warm-up stops.
10. Submit or inspect an order that IBKR rejects or cancels.

Create:

```text
docs/RUNTIME_DIAGNOSIS.md
```

The document must contain:

- observed issue;
- evidence;
- confirmed root cause;
- affected components;
- proposed fix.

No production fix should begin before the diagnosis is written.

---

## 4. Phase 2: Instrument Search and Contract Selection

### Backend

Add an endpoint such as:

```text
GET /api/v1/instruments/search/?query=...
```

The Backend should call the Gateway.

### Gateway

Add broker-backed instrument search using IBKR contract matching and contract details.

Each result should contain:

```json
{
  "symbol": "MSFT",
  "local_symbol": "MSFT",
  "conid": 272093,
  "asset_class": "STK",
  "exchange": "SMART",
  "primary_exchange": "NASDAQ",
  "currency": "USD",
  "description": "Microsoft Corporation"
}
```

### Frontend

Replace the simple ticker input with a debounced search component.

Flow:

```text
Type ticker or company
    ↓
Show matching broker contracts
    ↓
Select exact contract
    ↓
Qualify contract
    ↓
Create strategy
```

### Acceptance criteria

- Search is not limited to database instruments.
- A non-seeded ticker can be selected.
- Ambiguous contracts require explicit selection.
- The exact conId is persisted.
- No hardcoded AAPL or TSLA logic remains.

---

## 5. Phase 3: Dynamic Market-Data Subscriptions

Create a durable subscription model.

Suggested records:

```text
MarketDataSubscription
- instrument
- conid
- timeframe
- state
- consumer_count
- requested_at
- last_event_at
- last_error
```

### Subscription lifecycle

When a strategy is enabled:

1. Read its input requirements.
2. Create or reuse a subscription.
3. Send a subscription command to the Gateway.
4. Request historical bars for warm-up.
5. Start live market data.
6. Publish events into Kafka.
7. Restore active subscriptions after restart.

When a strategy is paused:

1. Reduce the reference count.
2. Cancel the broker subscription only when no active strategy requires it.

### Important constraints

- Only the Gateway may connect to IBKR.
- Subscriptions must be idempotent.
- Shared strategy inputs must reuse subscriptions.
- Restarts must not create duplicate subscriptions.
- Broker market-data permission errors must be stored and displayed.

---

## 6. Phase 4: Historical Warm-up

For every enabled strategy:

1. Calculate required warm-up bars.
2. Add a small safety margin.
3. Request enough historical data from IBKR.
4. Convert historical bars into the same canonical format used by live data.
5. Deduplicate historical/live overlap.
6. Persist final bars.
7. Compute indicators.
8. Trigger strategy evaluation when all required inputs are ready.

Warm-up progress must be calculated per strategy:

```text
usable final bars / required bars
```

Do not use a global market-bar count.

### Timeout behavior

If no progress occurs for a configured time:

- Do not remain in `WARMING_UP` forever.
- Set the strategy to `BLOCKED` or `DEGRADED`.
- Store a precise reason such as:
  - market-data permission missing;
  - no broker subscription;
  - no Kafka events;
  - Flink job stopped;
  - unknown instrument mapping;
  - Backend consumer stopped.

---

## 7. Phase 5: Dynamic Instrument Registry

Remove the environment-only dependency on:

```text
INSTRUMENT_SYMBOL_MAP
```

Replace it with a dynamic registry based on canonical instrument ID and conId.

The registry must update whenever a new contract is qualified.

Possible implementation:

1. Publish an instrument registry event to Kafka.
2. Flink consumes the registry through broadcast state.
3. Market events use conId or canonical instrument ID.
4. New instruments become available without restarting Flink.

### Acceptance criteria

- Newly qualified instruments are recognized immediately.
- No manual environment update is required.
- Unknown instruments are blocked with a useful reason.
- No valid instrument is silently sent to dead letter because of an outdated static map.

---

## 8. Phase 6: Order Cancellation and Rejection Diagnostics

### Gateway

Capture:

- order status;
- error code;
- error message;
- `whyHeld`;
- warning text;
- advanced reject JSON;
- trade log entries;
- event timestamp.

Publish durable broker-order events.

### Backend

Extend append-only order history with:

```text
broker_status
reason_code
reason
source
details
occurred_at
operator_requested
```

Status history must distinguish:

- operator cancellation;
- IBKR cancellation;
- IBKR rejection;
- inactive order;
- expiration;
- disconnect uncertainty.

### API

Add order detail endpoint:

```text
GET /api/v1/orders/<internal_id>/detail/
```

Return:

- order;
- status history;
- broker diagnostics;
- risk decision;
- fills;
- strategy attribution.

### Frontend

In the order drawer, show:

- chronological status timeline;
- broker error code;
- exact broker reason;
- source;
- time;
- operator-requested status.

When no reason exists, show:

```text
No broker reason received
```

Do not invent one.

---

## 9. Phase 7: Runtime Health Visibility

Add a clear streaming status section.

For each active strategy show:

- subscription state;
- conId;
- last raw event;
- last canonical event;
- last final bar;
- warm-up progress;
- last indicator;
- last strategy run;
- last error.

System health should show:

- Gateway connection;
- Kafka topic lag;
- Flink job state;
- Backend market consumer state;
- dead-letter count;
- stale instrument count.

A green system badge must not be shown when the strategy data path is broken.

---

## 10. Tests

### Instrument search

- Search returns multiple contracts.
- Non-seeded ticker works.
- Ambiguous ticker requires selection.
- Selected conId is persisted.
- New instrument reaches the dynamic registry.

### Market data and warm-up

- Enabling a strategy creates one subscription.
- Shared requirements reuse the same subscription.
- Historical bars advance warm-up.
- Historical/live overlap is deduplicated.
- Final bars create indicators.
- Ready inputs trigger one strategy run.
- Restart restores subscriptions.
- Missing permissions create a visible blocked state.
- No-data timeout prevents endless warm-up.

### Order diagnostics

- IBKR rejection reason reaches the Backend.
- Cancellation reason is stored.
- Operator and broker cancellation remain distinct.
- Order detail API returns ordered history.
- Frontend displays the exact reason.

### Regression

Run:

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm test && npm run build
cd .. && python -m pytest streaming/flink/tests
docker compose config --quiet
```

Also run existing Compose smoke and recovery scripts.

---

## 11. Completion Criteria

The work is complete only when:

- an instrument not previously stored can be searched and selected;
- its exact IBKR contract is qualified and persisted;
- its strategy receives historical and live data;
- warm-up progresses using real final bars;
- indicators and strategy runs appear;
- the streaming chain survives restarts;
- IBKR cancellation/rejection reasons appear in the order drawer;
- all tests pass;
- `docs/RUNTIME_DIAGNOSIS.md` contains confirmed evidence;
- no mock production data or hardcoded ticker workaround is used.
