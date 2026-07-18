# Trading Engine Full-Universe Recommendation System

## Implementation Plan: 500 Stocks, 97 Strategies, Simple Portfolio Builder

**Repository:** `rachitm0897/Trading-Engine`  
**Audited branch:** `main`  
**Audited commit:** `58af8bcb87b03a187ff50f4cedf0a66cd77c3572`

---

## 1. Product Goal

Replace the current 5-stock × 5-strategy MVP with a complete recommendation system using:

- all 500 stocks in the imported universe;
- all 97 strategy definitions;
- the complete GICS hierarchy;
- Finnhub and IBKR market/reference data;
- the existing risk, Portfolio Builder, preview, rebalance and SHADOW/PAPER safety systems.

The user-facing flow must be:

```text
Create or edit goals
→ choose allocation, timeframe and risk
→ click Generate recommendations
→ view recommended stocks, strategies and weights
→ preview the combined portfolio
→ explicitly apply through SHADOW/PAPER
```

The user must not:

- open a Research page;
- inspect strategy readiness;
- manually run experiments;
- manually accept each recommendation;
- manually add stocks;
- manually assign strategies;
- understand implementation status, feature readiness or backtest jobs.

All research complexity remains internal.

---

## 2. Current System Assessment

### 2.1 Working components to preserve

The repository already contains:

- the full 500-stock JSON universe;
- all 97 strategy hypotheses;
- GICS taxonomy and stock classification models;
- issuer, instrument and provider mapping;
- Finnhub and IBKR history integration;
- research daily bars and corporate actions;
- a single-asset backtest engine;
- a working 5×5 bootstrap pipeline;
- experiment and candidate-score persistence;
- a GICS-aware sleeve optimizer;
- goal recommendation models and API;
- immutable recommendation acceptance;
- fixed recommendation weights in construction preview;
- one combined rebalance;
- SHADOW/PAPER-only execution controls;
- frontend recommendation cards in Portfolio Builder.

### 2.2 Current limitations

The latest implementation is still explicitly pilot-bound:

- `apps/research/services/mvp.py` requires exactly five hardcoded stocks;
- it requires exactly five hardcoded runtime strategy keys;
- it creates a separate `RECOMMENDATION_MVP` universe;
- the experiment runner only supports single-asset daily strategies;
- strategy activity thresholds are hardcoded for five strategies;
- recommendation queries explicitly filter to the five symbols and five keys;
- the recommendation policy limits the result to five stocks;
- cache keys and Celery tasks are MVP-specific;
- the Research page exposes internal readiness and catalogue details;
- the System page exposes a Recommendation MVP panel;
- Portfolio Builder still contains manual stock and strategy editing;
- non-ready candidates can produce a user-facing `BLOCKED` result;
- only five runtime strategy plugins currently exist.

The next implementation must remove the MVP layer rather than extending its hardcoded lists.

---

## 3. Core Product Decisions

### 3.1 Simple frontend, sophisticated backend

The frontend exposes only:

1. goal allocation;
2. goal timeframe;
3. goal risk;
4. Generate recommendations;
5. recommendation results;
6. Preview;
7. Apply.

The backend continues to enforce:

- data quality;
- exact instrument identity;
- broker qualification;
- risk limits;
- cash floors;
- GICS limits;
- strategy compatibility;
- execution safety.

“Do not block the user” means no manual readiness workflow and no preventable `BLOCKED` screen. It does not mean bypassing risk or execution controls.

### 3.2 All 97 strategies have a role

Every strategy must receive an explicit implementation and one operational role:

| Role | Internal purpose | User-facing result |
|---|---|---|
| `EXECUTION` | Produces a long-only exposure stream for one stock | May be shown as the recommended stock strategy |
| `SELECTOR` | Ranks or filters stocks cross-sectionally | Influences which stocks are selected |
| `ALLOCATOR` | Selects portfolio weights | Influences recommended weights |
| `OVERLAY` | Adjusts cash, volatility, drawdown or exposure | Influences portfolio risk |
| `EVENT` | Changes scores around point-in-time events | Influences stock and strategy scores |
| `PAIR_BASKET` | Measures relative value or basket behaviour | Internal research signal only in the long-only builder |
| `INCOME` | Scores yield and income characteristics | Influences selection and may map to execution where exact |
| `RESEARCH_ONLY` | Cannot be represented safely in current long-only execution | Still implemented and backtested, but never creates an invalid runtime assignment |

The recommendation card displays only the primary executable long-only strategy for each stock.

Supporting selectors, allocators, overlays, event signals and relative-value models remain internal. Store their contribution for audit and explanation, but do not clutter the normal UI.

### 3.3 No runtime evaluation of JSON text

The JSON bundle remains the specification source.

Do not execute:

- formula strings;
- signal-description strings;
- natural-language rules;
- dynamically generated Python;
- `eval` or similar expression execution.

Each of the 97 strategies must have an explicit tested implementation class or explicit composed implementation.

### 3.4 All strategies are integrated, not necessarily order-producing

“All strategies” means:

- every imported strategy has an implementation;
- every strategy has data requirements;
- every strategy can be backtested through its correct engine;
- every strategy can contribute when its required data exists;
- every strategy has a compatibility result for each goal profile.

It does not mean forcing pair, short, basket, cross-sectional or allocator strategies into a single-stock live plugin.

---

## 4. Remove the MVP Architecture

Delete or replace:

- `Backend/apps/research/services/mvp.py`;
- `bootstrap_recommendation_mvp`;
- `run_recommendation_mvp_pipeline`;
- MVP-specific URLs and serializers;
- `RESEARCH_MVP_*` settings;
- `RECOMMENDATION_MVP` universe creation;
- MVP-specific cache keys;
- MVP-specific tests and documentation;
- exact five-stock and five-strategy constants;
- `MVP_WALK_FORWARD` experiment type;
- frontend MVP readiness types and queries.

Create:

```text
Backend/apps/research/services/universe_pipeline.py
Backend/apps/research/services/strategy_registry.py
Backend/apps/research/services/feature_pipeline.py
Backend/apps/research/services/experiment_factory.py
Backend/apps/research/services/recommendation_cache.py
Backend/apps/research/services/recommendation_batch.py
```

Rename the operator bootstrap command to:

```text
python manage.py bootstrap_recommendation_system
```

The active imported `US_LARGE_CAP_GICS` universe becomes the recommendation universe. Do not duplicate the 500 members into another universe.

---

## 5. Configuration

Replace MVP settings with:

```text
RESEARCH_ENABLED=true
RECOMMENDATION_SYSTEM_ENABLED=true
RECOMMENDATION_UNIVERSE_KEY=US_LARGE_CAP_GICS
RECOMMENDATION_MAX_STOCKS=20
RECOMMENDATION_MIN_STOCKS=5
RECOMMENDATION_CANDIDATE_POOL_SIZE=100
RECOMMENDATION_MAX_STRATEGIES_PER_STOCK=1
RESEARCH_DAILY_LOOKBACK_YEARS=10
RESEARCH_INTRADAY_LOOKBACK_DAYS=90
RESEARCH_MINIMUM_DAILY_BARS=756
RESEARCH_SCORE_MAX_AGE_DAYS=7
RESEARCH_STALE_SCORE_FALLBACK_DAYS=30
RECOMMENDATION_SNAPSHOT_MAX_AGE_HOURS=24
RESEARCH_MAX_PARALLEL_DATA_TASKS=8
RESEARCH_MAX_PARALLEL_BACKTEST_TASKS=8
RESEARCH_ARTIFACT_ROOT=/app/research_artifacts
```

Keep:

```text
ALLOW_LIVE_TRADING=false
NEW_EXECUTION_MODE=SHADOW
```

Settings must be parsed through one typed configuration object with validation.

Do not use environment variables to list 500 symbols or 97 strategy IDs. Load them from the active dataset.

---

## 6. Full Stock Universe Pipeline

### 6.1 Membership

Use all 500 active members from the active imported universe.

For each member maintain:

- issuer;
- canonical instrument;
- source symbol;
- verified provider symbol;
- GICS hierarchy;
- active membership;
- daily-data coverage;
- intraday-data coverage where required;
- corporate-action coverage;
- fundamental coverage;
- event coverage;
- last successful update;
- recommendation eligibility.

### 6.2 Instrument and provider mapping

Reuse:

- `Instrument`;
- `Issuer`;
- `InstrumentProviderMapping`;
- `BrokerContract`;
- current Finnhub verification;
- current IBKR qualification.

Do not create another mapping system.

Batch mapping workflow:

1. map by issuer and exact symbol;
2. verify Finnhub provider symbol;
3. preserve exchange and currency;
4. record ambiguity;
5. do not create fake broker contracts.

### 6.3 IBKR qualification strategy

Do not synchronously qualify all 500 contracts on every recommendation request.

Use two levels:

- background qualification for the complete universe in bounded batches;
- immediate qualification for finalists that do not yet have a contract.

During recommendation generation:

1. rank a larger candidate pool;
2. attempt exact IBKR qualification for finalists;
3. remove failed or ambiguous finalists;
4. substitute the next ranked candidate;
5. continue until the required result size is reached.

A single failed stock must never block the entire recommendation.

---

## 7. Data Architecture

### 7.1 Finnhub responsibilities

Use verified Finnhub symbols for:

- daily stock candles;
- intraday candles where available;
- company profile;
- splits;
- dividends;
- earnings calendar;
- recommendation trends;
- company financials and basic financials;
- estimates and revisions where available;
- corporate events required by the strategy catalogue.

Use incremental requests. Never refetch the complete history for all 500 stocks every day.

### 7.2 IBKR responsibilities

Use IBKR through `IB_gateway` for:

- exact contract identity;
- historical `TRADES`;
- historical `ADJUSTED_LAST`;
- historical schedule;
- intraday history fallback;
- data verification for selected candidates.

The Backend must not connect directly to TWS.

### 7.3 Provider precedence

For every dataset define a provider policy:

```text
primary provider
→ fallback provider
→ reconciliation tolerance
→ staleness threshold
→ required subscription
→ quality rules
```

For price data:

1. Finnhub primary;
2. IBKR `ADJUSTED_LAST` fallback;
3. IBKR `TRADES` verification;
4. preserve provider provenance and revisions.

### 7.4 Data coverage classes

Support these data families:

| Data family | Main strategies |
|---|---|
| Adjusted daily OHLCV | Baseline, trend, momentum, mean reversion, volatility |
| Intraday OHLCV/VWAP | Intraday and short-horizon strategies |
| Dividends and splits | Income, total-return and corporate-action strategies |
| Point-in-time fundamentals | Value, quality, profitability, investment and growth |
| Analyst estimates and recommendations | Revision and expectation strategies |
| Earnings and corporate events | Event strategies |
| GICS history | Sector-relative and peer strategies |
| Benchmark and sector returns | Beta, residual and relative momentum |
| Liquidity and spread proxies | Capacity and transaction-cost models |

### 7.5 Point-in-time guarantees

Every fundamental, recommendation, estimate and event record must include:

- event or period date;
- announced timestamp;
- public availability timestamp;
- provider timestamp;
- revision timestamp;
- data version.

Backtests may only access records available at the simulated decision timestamp.

### 7.6 Feature store

Do not recompute common features separately for every strategy.

Create a versioned feature store:

```text
InstrumentFeatureSnapshot
CrossSectionalFeatureSnapshot
MarketRegimeSnapshot
EventFeatureSnapshot
```

Store common daily features in partitioned Parquet artifacts and searchable summary metadata in PostgreSQL.

Feature identity includes:

- instrument or universe;
- feature key;
- frequency;
- date;
- data version;
- implementation version.

---

## 8. Complete Strategy Implementation Registry

### 8.1 Registry contract

Create a registry that covers every active imported strategy.

For every strategy define:

- research ID;
- implementation path;
- role;
- frequency;
- supported direction;
- data requirements;
- feature requirements;
- parameter schema;
- parameter budget;
- compatible goal timeframes;
- compatible risk levels;
- runtime mapping, if any;
- backtest engine;
- fallback behaviour;
- implementation version.

Startup and tests must fail when any of the 97 active strategy IDs lacks a registry entry.

### 8.2 Implementation packages

Organize explicit implementations by family:

```text
apps/research/implementations/
├── baseline.py
├── trend.py
├── momentum.py
├── mean_reversion.py
├── cross_sectional_factor.py
├── allocation.py
├── volatility_control.py
├── income.py
├── event.py
├── statistical_arbitrage.py
└── registry.py
```

### 8.3 Semantic validation

Every implementation must pass deterministic tests for:

- exact parameter names;
- valid parameter types;
- warm-up;
- feature availability;
- no future data;
- signal timing;
- next-bar execution;
- exposure bounds;
- role-appropriate output;
- deterministic output;
- long-only runtime mapping where applicable.

### 8.4 Runtime strategy definitions

Create new runtime `StrategyDefinition` and plugin classes only for strategies that can safely operate as long-only per-stock execution strategies.

Do not create runtime definitions for:

- selectors;
- allocators;
- overlays;
- pair/basket models;
- unsupported short-only strategies.

The recommendation output always selects an executable strategy for each stock, while all other strategy roles influence selection and weighting internally.

---

## 9. Scope-Aware Research Engines

### 9.1 Single-asset execution engine

Use for stock-specific trend, momentum, mean-reversion, income and baseline strategies.

Run only on stocks meeting each strategy’s data and liquidity requirements.

### 9.2 Cross-sectional engine

Run one universe-level experiment per strategy and date range, not 500 independent experiments.

It must support:

- ranking;
- quantile selection;
- sector neutrality;
- GICS-relative scores;
- residualisation;
- long-only top-bucket variants;
- turnover controls.

### 9.3 Allocation engine

Implement:

- equal weight;
- sector-neutral equal weight;
- inverse volatility;
- risk parity;
- minimum variance;
- maximum diversification;
- hierarchical risk parity;
- CVaR-based allocation where specified.

Allocation strategies produce portfolio weights, not per-stock runtime instances.

### 9.4 Overlay engine

Implement portfolio-level:

- volatility targeting;
- trend filters;
- drawdown controls;
- regime exposure;
- correlation shock reduction;
- liquidity scaling.

Overlays alter total exposure and cash, subject to current live rules.

### 9.5 Event engine

Use point-in-time:

- earnings;
- guidance;
- dividends;
- splits;
- analyst revisions;
- index and corporate actions.

Event strategies only emit signals after availability timestamps.

### 9.6 Statistical-arbitrage and pair/basket engine

Avoid all possible stock pairs.

Build candidate pairs through:

- same GICS industry or sub-industry;
- rolling correlation;
- liquidity;
- cointegration screening;
- bounded nearest-neighbour count.

These strategies may contribute relative-value and diversification scores.

They do not create invalid short or multi-instrument runtime assignments in the current long-only Portfolio Builder.

---

## 10. Scalable Experiment Scheduling

### 10.1 Do not run a raw 500 × 97 Cartesian product

Use role-aware scheduling:

- single-asset strategies: compatible stock-strategy pairs only;
- cross-sectional strategies: one panel experiment per universe/window;
- allocation strategies: one portfolio experiment per candidate set/window;
- overlays: one overlay experiment per base portfolio/window;
- event strategies: only instruments and dates with qualifying events;
- pair/basket strategies: only bounded peer candidates.

### 10.2 Experiment identity

Include:

- dataset version;
- protocol version;
- strategy implementation hash;
- feature version;
- instrument or universe;
- parameter hash;
- date range;
- provider-data version;
- role.

Reuse results when identity is unchanged.

### 10.3 Parameter control

Use:

- canonical parameters;
- deterministic bounded sampling;
- family-specific trial budgets;
- neighbouring-parameter tests;
- untouched final holdout;
- multiple-testing controls.

Do not run uncontrolled full grids.

### 10.4 Queues

Use separate Celery queues:

```text
research_mapping
research_daily_data
research_intraday_data
research_fundamentals
research_events
research_features
research_single_asset
research_cross_sectional
research_allocators
research_overlays
research_pairs
research_scoring
recommendation_cache
recommendations
```

Use Redis locks, bounded concurrency and resumable batches.

---

## 11. Candidate Scoring Architecture

Create role-specific scores.

### 11.1 Stock score

Combines:

- liquidity;
- data quality;
- GICS diversification value;
- selector scores;
- event scores;
- fundamental scores;
- volatility and drawdown fit;
- capacity.

### 11.2 Execution strategy score

Combines:

- out-of-sample performance;
- cost resilience;
- drawdown;
- stability;
- regime consistency;
- goal timeframe fit;
- goal risk fit;
- capacity.

### 11.3 Allocator score

Compares allocation methods using:

- portfolio volatility;
- drawdown;
- diversification;
- turnover;
- robustness;
- risk-profile fit.

### 11.4 Overlay score

Selects or combines overlays based on:

- current regime;
- target volatility;
- drawdown;
- liquidity;
- risk level.

### 11.5 Final sleeve score

For stock `i` and execution strategy `k`:

```text
final_score(i,k) =
    stock_selection_score(i)
  + execution_strategy_score(i,k)
  + diversification_contribution(i,k)
  + event_adjustment(i)
  - cost_penalty(i,k)
  - instability_penalty(i,k)
```

Store the contributing strategy IDs for audit, but show only the primary execution strategy in the normal UI.

---

## 12. Guaranteed Recommendation Availability

Remove user-facing `BLOCKED` recommendation results.

For every non-`NOW` goal use this fallback order:

### Tier 1: Current full model

Use fresh:

- full stock universe;
- all available strategy roles;
- current scores;
- current data;
- selected allocator and overlays.

### Tier 2: Last valid full snapshot

Use the most recent complete recommendation snapshot within the configured stale-score fallback period.

Refresh in the background.

### Tier 3: Price-only strategy fallback

Use current daily data with:

- fixed weight;
- buy and hold;
- trend;
- momentum;
- mean-reversion;
- volatility control.

Use diversified liquid stocks across GICS sectors.

### Tier 4: Baseline diversified fallback

Use:

- top liquid eligible stocks;
- GICS diversification;
- fixed-weight or buy-and-hold execution;
- live cash and stock caps.

### Tier 5: Existing valid snapshot

During provider outage, use the latest previously validated recommendation snapshot and display a small freshness note.

The user should not see readiness blockers or a research matrix.

A total first-run absence of all provider data is an operational deployment failure. Prevent it by running bootstrap and cache warming before the application is marked healthy.

---

## 13. Recommendation Cache

Precompute recommendations for every valid combination of:

- timeframe;
- risk;
- dataset version;
- as-of date.

Cache:

- candidate pool;
- selected stocks;
- selected execution strategy per stock;
- selected allocator;
- selected overlays;
- expected metrics;
- GICS exposure;
- fallback tier;
- data freshness.

Warm the cache:

- after daily data refresh;
- after score updates;
- after strategy implementation changes;
- after dataset activation.

User requests should mostly read cached research and perform only portfolio-specific turnover adjustment.

Target response time:

```text
1–5 seconds from a warm cache
```

---

## 14. Batch Recommendation API

Replace per-goal generate/accept friction with one plan-level operation.

### 14.1 Create recommendations

```text
POST /api/v1/portfolio-construction/plans/{plan_id}/recommendations/
```

The request needs only an idempotency key.

The service:

1. locks the plan;
2. snapshots all enabled goals;
3. loads the best cached recommendation for each timeframe/risk;
4. adjusts for current holdings and goal allocation;
5. qualifies or substitutes finalist stocks;
6. creates one recommendation per goal;
7. automatically attaches each completed recommendation to its goal;
8. updates `GoalInstrumentSelection`;
9. updates `GoalStrategyAssignment`;
10. preserves recommended fixed weights;
11. bumps the plan version once;
12. returns one batch run.

Generation and attachment create no:

- order;
- rebalance;
- strategy instance;
- strategy enablement.

### 14.2 Poll batch

```text
GET /api/v1/portfolio-construction/recommendation-batches/{batch_id}/
```

Return:

- overall status;
- result per goal;
- selected stocks;
- primary strategies;
- weights;
- timeframe;
- risk;
- metrics;
- fallback tier;
- freshness.

### 14.3 Regenerate

Calling the plan recommendation endpoint again replaces prior attached recommendations atomically.

The user does not need Accept or Detach actions.

### 14.4 Model additions

Add:

#### `RecommendationBatchRun`

- plan;
- requested plan version;
- status;
- idempotency key;
- input hash;
- dataset;
- protocol;
- created/completed timestamps;
- error;
- metrics.

#### `RecommendationBatchGoalResult`

- batch;
- goal;
- recommendation run;
- status;
- fallback tier;
- summary.

Keep existing goal recommendation and sleeve models.

---

## 15. Recommendation Construction

For each goal:

1. resolve live goal rules;
2. load all eligible stocks;
3. apply selector, event and fundamental scores;
4. retain the top candidate pool;
5. choose the highest-scoring executable strategy per stock;
6. qualify finalists through IBKR;
7. substitute failed finalists;
8. choose the best allocator;
9. apply overlays;
10. optimize weights;
11. enforce GICS and concentration rules;
12. store one strategy share of 100% per selected stock;
13. attach the recommendation to the goal.

Recommended stock count should vary by profile:

| Goal profile | Typical names |
|---|---:|
| HURRY | 5–8 |
| FAST | 6–10 |
| BUILD | 8–12 |
| GROW | 10–15 |
| COMPOUND | 12–20 |
| NOW | Cash only |

The live goal rules remain authoritative.

---

## 16. Frontend Simplification

### 16.1 Remove the Research UI

Delete:

- `/research` route;
- Research sidebar navigation;
- `ResearchUniversePage.tsx`;
- Research page styles;
- Research page tests;
- catalogue/readiness queries used only by that page;
- user-facing strategy readiness tables;
- user-facing 5×5 matrix.

Keep internal research administration in:

- Django admin;
- management commands;
- logs;
- audit records;
- metrics.

### 16.2 Remove Research from System page

Remove:

- Recommendation MVP metric;
- Recommendation MVP panel;
- MVP status query;
- readiness counts.

System remains focused on:

- gateway;
- market data provider connectivity;
- streaming;
- reconciliation;
- risk;
- audit.

### 16.3 Simplify Portfolio Builder

Replace the current four-step labels:

```text
Allocate goals
Add stocks & assign strategies
Preview
Apply
```

with:

```text
1. Goals
2. Recommendations
3. Preview & Apply
```

### 16.4 Goals step

The user sets:

- goal name;
- allocation percentage;
- timeframe;
- risk;
- enabled status.

Primary button:

```text
Save goals & generate recommendations
```

This saves goals and starts one batch recommendation.

### 16.5 Recommendations step

Show results grouped by goal.

Each recommendation card shows only:

- stock symbol and company;
- stock weight;
- primary strategy name;
- strategy timeframe;
- goal timeframe;
- goal risk;
- expected return;
- expected volatility;
- expected drawdown;
- short reason.

Actions:

- `Regenerate recommendations`;
- `Preview portfolio`;
- `Back to goals`.

Remove from normal frontend:

- manual stock search;
- manual stock addition;
- strategy assignment editors;
- ownership-share forms;
- Accept recommendation;
- Detach recommendation;
- readiness counts;
- blocked strategy lists;
- research dataset/protocol IDs;
- implementation-status labels.

The existing backend manual APIs may remain for internal compatibility, but the standard UI must not expose them.

### 16.6 Preview and Apply

Preview remains mandatory.

Apply remains explicit.

Show:

- goals;
- recommended holdings;
- strategy assignments;
- final merged stock targets;
- cash;
- expected metrics;
- rebalance changes.

Apply continues through the existing SHADOW/PAPER safety path.

---

## 17. Internal Observability

Removing the Research page must not remove operational visibility.

Add internal metrics:

- universe members mapped;
- daily data coverage;
- intraday coverage;
- fundamentals coverage;
- event coverage;
- feature freshness;
- strategy implementations registered;
- experiments completed;
- score freshness;
- cache freshness;
- recommendation latency;
- fallback-tier frequency;
- qualification substitutions;
- failed provider calls.

Expose these through:

- Django admin;
- structured logs;
- audit events;
- existing monitoring endpoints restricted to operators.

Do not expose them as a normal trading-page workflow.

---

## 18. Scheduling

Suggested schedule:

| Pipeline | Schedule |
|---|---|
| Universe and mapping refresh | Daily |
| Daily bars and corporate actions | After market close |
| Fundamentals and estimates | Daily |
| Events and earnings | Hourly |
| Intraday data for required strategies | During and after market hours |
| Common features | After relevant data update |
| Single-asset experiments | Incremental nightly |
| Cross-sectional experiments | Nightly |
| Allocation and overlay research | Weekly and after major score changes |
| Pair/basket screening | Weekly |
| Full robustness rerun | Monthly |
| Candidate scoring | After completed experiments |
| Recommendation cache warming | After scoring and daily refresh |

---

## 19. Database and Performance

### 19.1 PostgreSQL

Store:

- metadata;
- current readiness summaries;
- experiment identities;
- candidate scores;
- recommendations;
- audit records.

### 19.2 Artifact store

Store large data in Parquet:

- feature matrices;
- return series;
- trade series;
- cross-sectional panels;
- pair screens;
- attribution;
- robustness outputs.

### 19.3 Indexes

Add indexes for:

- active universe membership;
- instrument/date/version research bars;
- feature/date/version;
- strategy/role/status;
- candidate timeframe/risk/eligible/score;
- recommendation cache key;
- batch status;
- data freshness.

### 19.4 Bounded work

Never:

- load all 500 full histories into a web worker;
- create one task per raw parameter combination;
- compute all stock pairs;
- send all 500 stocks to the frontend;
- return full experiment artifacts through APIs.

---

## 20. Migration and Cleanup

### Backend

Remove:

- MVP settings;
- pilot universe;
- MVP command;
- MVP service;
- MVP endpoints;
- MVP caches;
- MVP experiment naming;
- hardcoded lists.

Migrate existing MVP data:

- retain valid research bars;
- retain experiments and scores when identities remain valid;
- map MVP implementation records into the full registry;
- retire the `RECOMMENDATION_MVP` universe;
- preserve existing accepted recommendations for audit.

### Frontend

Remove:

- Research route;
- Research nav;
- Research page;
- MVP status types;
- MVP status queries;
- Research panel on System;
- manual recommendation acceptance;
- manual stock and strategy assignment UI from standard Portfolio Builder.

### Documentation

Replace:

- `recommendation_mvp_implementation_plan.md`;
- `docs/RECOMMENDATION_MVP.md`.

Update:

- `README.md`;
- `.env.example`;
- `docs/RESEARCH_UNIVERSE.md`;
- `docs/BACKTESTING_PROTOCOL.md`;
- `docs/RECOMMENDATION_ENGINE.md`;
- `docs/STRATEGY_PROMOTION.md`;
- `docs/PORTFOLIO_BUILDER.md`;
- `docs/OPEN_QUESTIONS.md`.

---

## 21. Implementation Phases

### Phase 1: Remove pilot boundaries

- add full-universe configuration;
- replace `mvp.py`;
- remove exact five-stock/five-strategy validation;
- use the active 500-stock universe;
- retain current working data and history code.

### Phase 2: Full data coverage

- batch-map all 500 Finnhub symbols;
- implement incremental daily data;
- add fundamentals, estimates and events;
- complete IBKR fallback;
- create data-coverage summaries;
- pre-qualify and lazily qualify contracts.

### Phase 3: All 97 strategy implementations

- create family implementation modules;
- create a complete registry;
- implement all roles;
- add semantic validation;
- fail tests when any strategy lacks an implementation.

### Phase 4: Scope-aware research engines

- complete cross-sectional engine;
- complete allocator engine;
- complete overlay engine;
- complete event engine;
- complete bounded pair/basket engine;
- preserve single-asset engine.

### Phase 5: Feature store and scalable experiments

- precompute common features;
- create role-aware experiments;
- add bounded parameter sampling;
- add incremental invalidation;
- add Parquet artifacts.

### Phase 6: Role-specific scoring

- calculate stock, strategy, allocator and overlay scores;
- create final sleeve scores;
- cache results by timeframe and risk;
- add fallback tiers.

### Phase 7: Plan-level recommendation flow

- add batch models;
- add plan recommendation endpoint;
- auto-attach completed recommendations;
- automatically substitute failed contracts;
- remove user-facing blocked results.

### Phase 8: Frontend simplification

- remove Research page and navigation;
- remove System research panel;
- reduce Portfolio Builder to three steps;
- remove manual stock/strategy configuration from normal flow;
- show clean recommendation cards;
- preserve Preview and Apply.

### Phase 9: Performance and operations

- add queues;
- add locks;
- add scheduling;
- add monitoring;
- benchmark data refresh, experiment throughput and recommendation latency.

### Phase 10: Verification and cleanup

- remove dead MVP code;
- migrate retained data;
- update documentation;
- run all tests;
- run Docker smoke tests;
- verify every timeframe and risk profile.

---

## 22. Test Plan

### 22.1 Universe

Verify:

- exactly 500 active members;
- all 11 GICS sectors represented;
- every member has issuer and GICS;
- mapping is deterministic;
- failed mappings do not block other stocks;
- finalist substitution works.

### 22.2 Data

Test:

- Finnhub daily and intraday retrieval;
- verified provider symbols;
- IBKR history fallback;
- corporate actions;
- fundamentals;
- analyst data;
- events;
- point-in-time availability;
- revisions;
- staleness;
- provider outage fallback;
- incremental refresh.

### 22.3 Strategies

Verify:

- all 97 active strategy IDs have registry entries;
- all implementation paths load;
- all parameter schemas validate;
- every strategy uses the correct engine;
- no JSON formula is executed;
- every long-only runtime mapping is exact;
- selectors and allocators do not create fake strategy instances;
- pair/basket models do not create invalid single-stock orders.

### 22.4 Experiments

Test:

- role-aware scheduling;
- no raw Cartesian explosion;
- deterministic experiment identity;
- idempotent reruns;
- implementation and data invalidation;
- bounded pair screening;
- final holdout;
- costs;
- multiple testing;
- parameter stability.

### 22.5 Recommendations

Test every valid timeframe/risk combination.

Verify:

- all 500 stocks may enter the candidate universe;
- all compatible strategies may contribute;
- at most one primary execution strategy per stock;
- stock count follows goal profile;
- GICS diversification;
- cash floor;
- stock cap;
- turnover;
- contract substitution;
- current cache;
- stale-cache fallback;
- price-only fallback;
- baseline fallback;
- no user-facing `BLOCKED` result;
- NOW remains cash only.

### 22.6 Frontend

Verify:

- no Research navigation;
- no `/research` route;
- no Research panel on System;
- Goals step contains only goal fields;
- one Generate recommendations action handles all goals;
- recommendations show stock, strategy, timeframe and risk;
- no Accept or Detach action;
- no manual stock/strategy forms in standard flow;
- Preview is mandatory;
- Apply is explicit;
- loading and regeneration are smooth.

### 22.7 Safety

Verify:

- generation creates no orders;
- generation creates no rebalance;
- generation creates no strategy instances;
- Preview creates no order;
- Apply remains explicit;
- strategy instances remain disabled SHADOW;
- LIVE trading remains impossible;
- kill switch and reconciliation remain unchanged.

### 22.8 Performance

Targets:

- warm recommendation response: 1–5 seconds;
- no web-worker research;
- no unbounded Celery fan-out;
- bounded API payload;
- full daily refresh resumes after failure;
- cache warming finishes independently of user requests.

---

## 23. End-to-End Acceptance Scenario

The implementation is complete only when:

1. the active bundle contains 500 stocks and 97 strategies;
2. all 500 stocks are loaded into the active recommendation universe;
3. all 97 strategies have explicit implementations;
4. daily data is maintained incrementally;
5. required fundamentals and events are stored point-in-time;
6. strategy engines produce current candidate scores;
7. caches exist for every valid timeframe/risk combination;
8. the Research route and navigation no longer exist;
9. the System page has no Research/MVP panel;
10. the user creates goals with allocation, timeframe and risk;
11. the user clicks one Generate recommendations button;
12. the system returns recommendations for every enabled goal;
13. each result shows stocks, primary strategies, weights, timeframe and risk;
14. unavailable candidates are substituted automatically;
15. provider issues use cached or baseline fallback;
16. recommendations attach automatically to goals;
17. the user previews the combined portfolio;
18. preview preserves recommended weights;
19. the user explicitly applies;
20. one SHADOW/PAPER rebalance is created;
21. strategy instances remain disabled;
22. no LIVE order path is introduced.

---

## 24. Verification Commands

Run:

```bash
cd Backend
pytest
python manage.py check
python manage.py makemigrations --check
python manage.py validate_research_bundle ../Trading_Engine_Stock_Strategy_Universe_JSON
python manage.py import_research_bundle ../Trading_Engine_Stock_Strategy_Universe_JSON --activate
python manage.py bootstrap_recommendation_system
python manage.py warm_recommendation_cache
```

Then:

```bash
cd ../IB_gateway
pytest
```

Then:

```bash
cd ../Frontend
npm install
npm test
npm run build
```

Then:

```bash
cd ..
./.venv/Scripts/python -m pytest streaming/flink/tests
docker compose config --quiet
```

Run a Docker smoke test with:

```text
RESEARCH_ENABLED=true
RECOMMENDATION_SYSTEM_ENABLED=true
NEW_EXECUTION_MODE=SHADOW
ALLOW_LIVE_TRADING=false
```

---

## 25. Non-Goals

Do not:

- expose a Research page;
- expose strategy implementation status to normal users;
- execute JSON formulas;
- generate fake scores;
- force every strategy into a live plugin;
- create short positions in the current long-only builder;
- brute-force every stock pair;
- qualify all contracts synchronously during user requests;
- bypass risk, cash or execution safety;
- auto-apply a rebalance;
- enable strategy instances automatically;
- add LIVE trading;
- keep dead MVP compatibility branches after migration.

---

## 26. Implementation Discipline

- Follow the phases in order.
- Read existing code before modifying each area.
- Reuse current models and services where their semantics remain correct.
- Replace the MVP cleanly rather than layering another system above it.
- Keep internal research rigorous while making the user flow simple.
- Add tests with each phase.
- Keep all jobs idempotent and resumable.
- Remove replaced code completely.
- Record unavoidable assumptions in `docs/OPEN_QUESTIONS.md`.
- Finish with a working full-universe recommendation flow, not another catalogue or readiness dashboard.
