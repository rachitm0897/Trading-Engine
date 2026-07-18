# Trading Engine Recommendation MVP

## 5 Stocks × 5 Strategies Implementation Plan

**Repository:** `rachitm0897/Trading-Engine`  
**Audited branch:** `main`  
**Audited commit:** `935ed3d43a0fd9377fbaeb51f339cbaaa5e4e829`

## 1. Required Product Flow

The product must work like this:

```text
User creates a goal
→ selects timeframe
→ selects risk
→ clicks Generate recommendation
→ receives stocks, strategies and weights
→ reviews and accepts
→ previews the combined portfolio
→ explicitly applies through SHADOW/PAPER
```

The user must not manually run strategies from the research catalogue.

Keep the full 500-stock and 97-strategy catalogue for future expansion, but make only a controlled 5-stock × 5-strategy pilot operational now.

## 2. Current Codebase State

Already implemented and must be reused:

- research dataset and GICS models;
- imported 500-stock and 97-strategy catalogue;
- issuer and instrument mapping;
- Finnhub provider mappings;
- exact IBKR contract qualification;
- research daily-bar models;
- Wave 0 strategy classes;
- single-asset backtest engine;
- candidate-score and recommendation models;
- recommendation API;
- recommendation acceptance;
- Portfolio Builder recommendation controls;
- accepted fixed-weight construction;
- existing Preview and Apply flow;
- SHADOW/PAPER-only safety.

Current blockers:

1. `RESEARCH_ENABLED` defaults to false.
2. Wave 0 implementations are not automatically registered and validated.
3. No normal process creates the 25 required experiments.
4. Operational bars are staged as `SUSPECT`, while experiments require `VALID`.
5. Experiment results do not populate all scoring fields.
6. Promotion requires scores before experiments can run, creating a circular dependency.
7. The recommendation service therefore finds no approved candidates.
8. The frontend shows a recommendation action, but usually receives only `NO_APPROVED_CANDIDATES`.

Do not replace the current recommendation architecture. Complete the missing pipeline.

## 3. Fixed Pilot Stocks

Use exactly:

| Symbol | Company | Sector |
|---|---|---|
| AAPL | Apple | Information Technology |
| JPM | JPMorgan Chase | Financials |
| XOM | Exxon Mobil | Energy |
| JNJ | Johnson & Johnson | Health Care |
| WMT | Walmart | Consumer Staples |

Rules:

- resolve them from the imported research universe;
- keep imported issuer and GICS metadata;
- require verified Finnhub mapping;
- require exact IBKR contract qualification before actionable recommendation;
- do not silently replace a blocked stock;
- show the precise readiness reason.

The full 500-stock universe remains catalogued, but only these five are enabled for MVP recommendations.

## 4. Fixed Pilot Strategies

Use exactly these existing runtime keys:

1. `FIXED_WEIGHT_REBALANCE`
2. `SMA_CROSSOVER`
3. `RSI_MEAN_REVERSION`
4. `DONCHIAN_BREAKOUT`
5. `VOLATILITY_TARGET_MOMENTUM`

Requirements:

- link each runtime strategy to one exact research strategy definition;
- use or correct the existing Wave 0 research adapter;
- verify semantic parity before marking the mapping exact;
- backtest all five strategies on all five stocks;
- generate 25 stock-strategy candidates;
- select at most one strategy per stock in the MVP recommendation.

The fixed-weight strategy remains the baseline and may win when active strategies do not beat it after costs and risk adjustment.

## 5. Configuration

Add and validate:

```text
RESEARCH_ENABLED=true
RESEARCH_MVP_ENABLED=true
RESEARCH_MVP_STOCKS=AAPL,JPM,XOM,JNJ,WMT
RESEARCH_MVP_STRATEGIES=FIXED_WEIGHT_REBALANCE,SMA_CROSSOVER,RSI_MEAN_REVERSION,DONCHIAN_BREAKOUT,VOLATILITY_TARGET_MOMENTUM
RESEARCH_MVP_MINIMUM_BARS=756
RESEARCH_MVP_LOOKBACK_YEARS=5
RESEARCH_MVP_MAX_STOCKS=5
RESEARCH_MVP_MAX_STRATEGIES_PER_STOCK=1
```

Keep:

```text
ALLOW_LIVE_TRADING=false
NEW_EXECUTION_MODE=SHADOW
```

Parse pilot settings through one typed service. Do not scatter raw environment parsing across the codebase.

## 6. Market Data

### Responsibilities

- IBKR: canonical contract, conId, exchange, currency and tradability.
- Finnhub: primary daily historical data.
- IBKR historical bars: fallback and verification source.

The Backend must never connect directly to TWS. All IBKR requests go through `IB_gateway`.

### Finnhub changes

Use verified `InstrumentProviderMapping.provider_symbol`, not raw `Instrument.symbol`.

Fetch and normalize:

- daily OHLCV;
- dividends;
- splits;
- corporate actions;
- provider timestamps;
- revision metadata.

Store versions in `ResearchDailyBar` and `ResearchCorporateAction`.

### IBKR fallback

Add an authenticated read-only gateway endpoint:

```text
POST /api/v1/market-data/history/
```

Support only bounded daily requests for the five pilot stocks.

Request fields:

- conId;
- symbol;
- exchange;
- currency;
- bar size;
- duration;
- `TRADES` or `ADJUSTED_LAST`;
- regular-hours flag;
- end time.

Add a typed Backend `GatewayClient` method.

### Data validation

A stock becomes research-ready only when:

- at least 756 daily bars exist;
- OHLC is positive and consistent;
- dates are unique and sorted;
- volume is non-negative;
- the latest bar is not stale;
- no future revision is used;
- splits and dividends are reconciled;
- adjusted OHLC is available;
- missing-session ratio is acceptable;
- provider mapping is verified.

Mark failed series `SUSPECT` or `REJECTED` with explicit reasons. Never convert suspect data to valid merely to unblock the UI.

## 7. Bootstrap Command

Create one idempotent command:

```text
python manage.py bootstrap_recommendation_mvp
```

It must:

1. verify research is enabled;
2. verify an active dataset and protocol;
3. locate the five stocks;
4. map instruments;
5. verify Finnhub mappings;
6. report missing IBKR contracts;
7. create/update the pilot universe;
8. register five strategy implementations as `DRAFT`;
9. run semantic validation;
10. mark passing adapters `VALIDATED`;
11. refresh research data;
12. calculate stock eligibility;
13. create all 25 experiments;
14. execute changed trials;
15. calculate complete validation metrics;
16. create candidate scores;
17. approve passing implementations;
18. update builder readiness;
19. output a 5 × 5 readiness matrix.

It must not create fake contracts, guess ambiguous contracts, place orders, enable strategies or bypass failed checks.

## 8. Fix Strategy Lifecycle

Use:

```text
CATALOGUED
→ DRAFT
→ VALIDATED
→ BACKTESTED
→ SCORED
→ APPROVED_FOR_RECOMMENDATION
→ SHADOW_VALIDATED
→ BUILDER_READY
```

Registration and semantic validation must not require a candidate score.

The experiment runner may run `VALIDATED` or `APPROVED` implementations.

Promotion occurs after backtesting and scoring.

Historical research must not require prior SHADOW validation. Require SHADOW validation only for `builder_ready=true`.

Semantic tests must cover:

- parameter names and types;
- defaults;
- long-only behavior;
- exposure range;
- signal timing;
- next-bar execution;
- entry/exit behavior;
- warm-up;
- deterministic output;
- parity with the corresponding runtime plugin.

## 9. Experiment Factory

Create deterministic experiments for every stock-strategy pair.

Experiment identity must include:

- dataset version;
- protocol version;
- stock;
- strategy;
- implementation hash;
- data version;
- parameter hash;
- date range.

Reuse completed trials when inputs are unchanged. Invalidate them when data or implementation changes.

Maximum trial counts per stock:

| Strategy | Trials |
|---|---:|
| Fixed weight | 1 |
| SMA | 6 |
| RSI | 8 |
| Donchian | 6 |
| Volatility-target momentum | 8 |

Read parameter names and constraints from existing plugin schemas.

## 10. Backtesting

Use:

- daily adjusted OHLCV;
- signal at bar `t`;
- execution at bar `t+1` open;
- long-only exposure between 0 and 1;
- commission;
- spread;
- market-impact proxy;
- participation cap.

Pilot validation:

- up to five years of data;
- final six months untouched;
- at least three independent test windows when possible;
- purge and embargo;
- no tuning on final holdout.

Calculate:

- total return;
- CAGR;
- volatility;
- Sharpe;
- Sortino;
- Calmar;
- maximum drawdown;
- turnover;
- trade count;
- exposure;
- win rate;
- profit factor;
- cost;
- 25 and 50 bps stress results;
- capacity;
- subperiod dependence;
- parameter stability;
- regime consistency;
- holdout result;
- deflated Sharpe;
- multiple-testing result.

Use strategy-specific activity thresholds. Do not reject the fixed-weight baseline because it has few discrete trades.

## 11. Scoring and Approval

Populate every field expected by the existing scoring service.

Hard rejections include:

- bad or stale data;
- leakage;
- negative high-cost result;
- excessive drawdown;
- insufficient strategy-specific activity;
- unstable parameters;
- capacity failure;
- subperiod dependence;
- multiple-testing failure;
- unprotected holdout.

Create scores for every supported combination of:

- stock;
- strategy;
- timeframe;
- risk.

Use the current `resolved_goal_rules` as the authoritative risk model.

`NOW` remains cash only.

## 12. Recommendation Logic

For a non-`NOW` goal:

1. load current non-expired scores;
2. restrict to five pilot stocks;
3. restrict to five pilot strategies;
4. require valid data;
5. require exact IBKR qualification;
6. require builder-ready strategy;
7. apply timeframe compatibility;
8. apply risk compatibility;
9. choose the best strategy per stock;
10. optimize up to five stock-strategy sleeves;
11. apply live cash, stock, GICS and turnover constraints;
12. save an immutable recommendation.

Pilot policy:

```text
number_of_stocks = 5
maximum_strategies_per_stock = 1
minimum_candidate_score = 65
minimum_cash = resolved goal rule
per_stock_cap = resolved goal rule
minimum_sectors = min(3, selected stock count)
```

Do not keep the current 20-stock default.

For non-`NOW` goals, zero candidates must produce `BLOCKED`, not a misleading successful cash recommendation.

Return blocker codes such as:

- `RESEARCH_DISABLED`;
- `FINNHUB_MAPPING_MISSING`;
- `IBKR_CONTRACT_NOT_QUALIFIED`;
- `INSUFFICIENT_VALID_HISTORY`;
- `NO_VALIDATED_IMPLEMENTATION`;
- `NO_PASSING_BACKTEST`;
- `NO_CANDIDATE_FOR_TIMEFRAME_RISK`.

## 13. Acceptance and Portfolio Builder

Reuse the existing acceptance flow.

Acceptance must:

- validate recommendation freshness;
- validate plan version;
- recheck stock and strategy readiness;
- populate `GoalInstrumentSelection`;
- populate one `GoalStrategyAssignment` per stock;
- set strategy share to 100%;
- preserve recommended stock weights;
- switch the goal to accepted-recommendation mode;
- record an audit event;
- require the user to Preview separately.

It must not create orders, rebalances or strategy instances.

Preview and Apply remain mandatory.

Apply continues to create one combined SHADOW/PAPER rebalance and disabled strategy instances.

## 14. Frontend

### Portfolio Builder

For every non-`NOW` goal show:

- Generate recommendation;
- readiness status;
- selected stocks;
- GICS sectors;
- selected strategies;
- weights;
- candidate scores;
- expected return;
- volatility;
- drawdown;
- reason;
- data source;
- latest data date;
- expiry;
- Accept;
- Regenerate;
- Detach;
- Manual mode.

Display exact blockers rather than one generic no-candidate message.

### Research page

Add a 5 × 5 matrix:

| Stock / Strategy | Fixed | SMA | RSI | Donchian | Vol-Target |
|---|---|---|---|---|---|

Each cell shows:

- data missing;
- ready;
- queued;
- failed;
- score;
- approved;
- builder ready.

Per stock show:

- Finnhub status;
- IBKR status;
- valid-bar count;
- latest date;
- provider;
- eligibility blockers.

### System page

Show:

- research enabled status;
- Finnhub configuration;
- IBKR connection;
- pilot stock readiness;
- last data refresh;
- last experiment run;
- eligible candidate count.

Administrative mutation remains command-line only until API permissions are implemented.

## 15. APIs and Tasks

Reuse current recommendation endpoints.

Add bounded read-only endpoints:

```text
GET /api/v1/research/mvp/status/
GET /api/v1/research/mvp/matrix/
GET /api/v1/research/mvp/stocks/
GET /api/v1/research/mvp/strategies/
```

Celery pipeline:

```text
refresh five stocks
→ validate data
→ calculate eligibility
→ run changed experiments
→ calculate metrics
→ score candidates
→ update readiness
→ warm recommendation cache
```

Run after market close, with bounded concurrency, Redis locks and idempotency.

## 16. Main File Areas

Backend:

- `apps/research/services/mvp.py`
- implementation registry
- research-data service
- experiment factory and runner
- scoring and promotion
- recommendations
- tasks and commands
- readiness views
- portfolio-construction blocker propagation
- Finnhub provider integration
- Gateway client

IB Gateway:

- historical-bar view;
- adapter method;
- validation;
- mocked tests.

Frontend:

- Portfolio Builder recommendation panel;
- research matrix;
- System status;
- API types and queries;
- frontend tests.

Documentation:

- README;
- `.env.example`;
- research universe;
- backtesting protocol;
- recommendation engine;
- strategy promotion;
- Portfolio Builder.

## 17. Tests

Required coverage:

- exactly five pilot stocks and five strategies;
- GICS resolution;
- Finnhub symbol mapping;
- exact IBKR qualification;
- Finnhub history;
- IBKR fallback;
- splits and dividends;
- valid/suspect/rejected bars;
- 756-bar rule;
- deterministic strategy signals;
- next-bar execution;
- long-only exposure;
- 25 experiment groups;
- idempotent experiment creation;
- complete scoring metrics;
- timeframe and risk filtering;
- one strategy per stock;
- fixed-weight baseline allowed to win;
- zero candidates return BLOCKED;
- blocker display in frontend;
- accepted weights survive Preview;
- recommendation and acceptance create no orders;
- Apply remains explicit;
- SHADOW/PAPER safety remains intact;
- manual Portfolio Builder remains functional.

## 18. End-to-End Acceptance

The work is complete only when:

1. research is enabled;
2. the JSON bundle is active;
3. the bootstrap command runs successfully;
4. five stocks are mapped;
5. five stocks have valid historical data;
6. five stocks have exact IBKR contracts;
7. five strategies are validated;
8. all 25 stock-strategy groups are backtested;
9. passing scores exist;
10. a user selects timeframe and risk;
11. Generate Recommendation returns one to five combinations;
12. the frontend shows stocks, strategies, weights, metrics and reasons;
13. the user accepts;
14. Preview preserves recommendation weights;
15. the user explicitly applies;
16. one SHADOW/PAPER rebalance is created;
17. strategy instances remain disabled;
18. no LIVE path exists.

## 19. Verification

Run:

```bash
cd Backend
pytest
python manage.py check
python manage.py makemigrations --check
python manage.py validate_research_bundle ../Trading_Engine_Stock_Strategy_Universe_JSON
python manage.py import_research_bundle ../Trading_Engine_Stock_Strategy_Universe_JSON --activate
python manage.py bootstrap_recommendation_mvp

cd ../IB_gateway
pytest

cd ../Frontend
npm install
npm test
npm run build

cd ..
./.venv/Scripts/python -m pytest streaming/flink/tests
docker compose config --quiet
```

Run a Docker smoke test with research enabled and SHADOW execution.

## 20. Non-Goals

Do not implement now:

- all 500 stocks in active recommendations;
- all 97 strategies;
- cross-sectional, pair, basket, short or intraday strategies;
- automatic contract guessing;
- fake scores;
- automatic orders;
- automatic strategy enablement;
- LIVE trading;
- runtime execution of JSON formulas;
- unauthenticated administrative mutation APIs;
- treating suspect data as valid.

## 21. Discipline

- Follow the phases in order.
- Reuse the existing recommendation and Portfolio Builder architecture.
- Do not create a second provider mapping or recommendation system.
- Do not bypass readiness checks.
- Keep operations idempotent.
- Add tests with each phase.
- Remove replaced incomplete paths.
- Record assumptions in `docs/OPEN_QUESTIONS.md`.
- Finish with a working end-to-end recommendation flow, not just models and catalogue pages.
