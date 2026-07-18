# Recommendation engine

The online path reads precomputed snapshots; it does not launch backtests or load 500 full histories in a web worker. Scores combine current liquidity, data quality, GICS diversification, selector/income ranks, point-in-time event adjustments, volatility/drawdown fit, capacity, and eligible execution-strategy evidence. Allocator and overlay scores are selected separately. Audit records retain all contributing catalogue IDs, while the normal UI shows one primary executable long-only strategy per stock.

All active members of `US_LARGE_CAP_GICS` may enter the candidate pool. Recommended name counts vary by goal: HURRY 5–8, FAST 6–10, BUILD 8–12, GROW 10–15, COMPOUND 12–20, and NOW cash only. The live goal rules remain authoritative for cash floors and stock caps. The sleeve optimizer additionally enforces sector, industry, sub-industry, liquidity, capacity, and portfolio-specific turnover constraints.

Availability is deterministic:

1. fresh full-model snapshot;
2. last valid full snapshot within the stale window;
3. current price-only model;
4. diversified liquid buy-and-hold baseline;
5. latest validated deployment snapshot.

A missing deployment snapshot is an operational failure, not a user-facing `BLOCKED` recommendation. Every result records the fallback tier and freshness. Exact IBKR qualification occurs only for finalists; failures are replaced from the ranked candidate pool. Failed provider work is isolated per member and recorded in logs, audit, and operator metrics.

## Plan-level API

```text
POST /api/v1/portfolio-construction/plans/{plan_id}/recommendations/
GET  /api/v1/portfolio-construction/recommendation-batches/{batch_id}/
```

POST requires an `Idempotency-Key` and an empty object/body. It locks and snapshots the plan, processes all enabled goals atomically, attaches fixed recommendations, updates selections/assignments, and bumps the plan version once. Calling it again regenerates and replaces the attached recommendation rows.

Generation creates no order, rebalance, strategy instance, enablement, preview, or LIVE path. Preview remains mandatory and creates no order. Apply remains an explicit separate action through the existing SHADOW/PAPER rebalancing, risk, sizing, OMS, Gateway, ledger, and reconciliation controls. Created or updated strategy instances remain disabled in SHADOW.

Warm all valid timeframe/risk caches with:

```powershell
python manage.py warm_recommendation_cache
```

The cache is also scheduled after data, feature, score, and dataset changes. Operator `/metrics` exposes universe/data coverage, feature and score age, registry/experiment counts, cache age, latency, fallback frequency, substitutions, and provider failures.

`/healthz` remains a liveness probe. `/readyz` is the deployment-readiness gate: it returns 200 only when the complete active universe and registry load and all 20 valid timeframe/risk cache profiles are current. A first deployment with no provider data or validated snapshot therefore remains not ready instead of exposing a user-facing `BLOCKED` workflow.
