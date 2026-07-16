# Finnhub market-data fallback

Finnhub is a Backend-only market-data fallback. It has no account, position, order, execution, commission, contract-qualification, or trading authority. IBKR remains the sole broker and all execution remains paper-only.

The fallback path is:

```text
Finnhub REST/WebSocket -> Backend provider arbitration -> transactional OutboxEvent
-> market.raw.v1 -> canonical conId validation -> Flink bars/indicators -> strategies
```

Every eligible instrument must first have a qualified IBKR `BrokerContract` and a `VERIFIED` Finnhub `InstrumentProviderMapping`. Automatic and manual verification both require matching symbol/local-symbol, currency, stock type, and primary-exchange evidence. Ambiguous, unsupported, and unverified mappings fail closed.

Provider state is stored per `MarketDataSubscription`. Each switch creates a new UUID generation and an immutable `MarketDataProviderTransition`. Backend rejects events from the wrong provider or generation before creating the outbox record. Canonical instrument/timeframe/window idempotency prevents cross-provider duplicate windows.

The supervised `consume_finnhub_market_data` Backend process maintains the WebSocket, reconciles desired fallback symbols, deduplicates trades, and emits UTC-aligned final 5-second OHLCV bars after the configured lateness interval. Celery only performs finite health, mapping, and provider-arbitration checks.

## Safe defaults and rollout

All fallback feature flags default to `false`:

```text
MARKET_DATA_FALLBACK_ENABLED=false
FINNHUB_HISTORICAL_FALLBACK_ENABLED=false
FINNHUB_LIVE_FALLBACK_ENABLED=false
FINNHUB_AUTO_FAILBACK_ENABLED=false
```

Set a Finnhub Premium credential through `FINNHUB_API_KEY` or the existing encrypted provider configuration API. The credential is sent in a REST header and used only while opening the WebSocket; status, audit, metrics, errors, and logs never contain it.

Before enabling fallback, qualify the IBKR stock contract and inspect or verify its mapping:

```text
GET  /api/v1/data-providers/finnhub/mappings/
POST /api/v1/data-providers/finnhub/mappings/<instrument_id>/
GET  /api/v1/data-providers/finnhub/
GET  /api/v1/streaming/health/
```

The mapping POST requires an `Idempotency-Key` and `provider_symbol`. It verifies provider metadata rather than trusting the submitted ticker.

On IBKR failure, Backend fetches required Finnhub history when historical fallback is enabled, records reference-price provenance, activates WebSocket fallback, and continues through Kafka/Flink. If Finnhub is also unusable, dependent strategies are blocked. While fallback is active, Backend probes IBKR with a separate generation. It promotes IBKR only after fresh live events reach `PRIMARY_RECOVERY_CONFIRMATION_EVENTS` at a clean 5-second boundary; delayed Finnhub events are then rejected.

No setting in this feature enables live trading. `ALLOW_LIVE_TRADING=true` remains a startup error and `NEW_EXECUTION_MODE` remains restricted to `SHADOW` or `PAPER`.

Run the mocked takeover/recovery smoke test inside the built Backend image without brokerage credentials or a Finnhub key:

```text
docker compose exec backend pytest tests/test_finnhub_fallback_smoke.py
```
