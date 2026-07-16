# Trading Engine Stock and Strategy Universe Integration

## Updated Implementation Plan

**Repository:** `rachitm0897/Trading-Engine`  
**Audited branch:** `main`  
**Audited commit:** `d7a26521b43a5a561b66b5889ef87035d065ee95`  
**Source bundle already present in the repository:** `Trading_Engine_Stock_Strategy_Universe_JSON/`

---

## 1. Objective

Integrate the copied stock and strategy universe into the existing Trading Engine as a versioned research, validation, scoring, and portfolio-recommendation system.

The completed system must:

1. validate and import the supplied JSON bundle;
2. store the 500-stock universe and complete GICS hierarchy;
3. store all 97 strategy hypotheses without pretending they are executable;
4. build point-in-time research data and data-readiness checks;
5. backtest eligible stock-strategy combinations with the supplied protocol;
6. score and approve stable candidates;
7. generate a fast stock-and-strategy portfolio for a goal's timeframe and risk;
8. preserve the exact recommended stock and strategy-sleeve weights through Portfolio Builder preview;
9. require the current manual preview and apply flow before any rebalance;
10. preserve the existing SHADOW/PAPER-only and disabled-strategy safety boundaries.

The JSON files are research specifications and metadata. They are not runtime strategy code and must never be interpreted with `eval`, arbitrary expressions, or generated code at execution time.

---

## 2. Current Repository State

### 2.1 Work already completed

The previous stock/strategy Portfolio Builder refactor is implemented and must not be rebuilt.

The repository already contains:

- `GoalInstrumentSelection` for goal stock selection;
- `GoalStrategyAssignment` for one or more strategies per stock;
- explicit `strategy_share` ownership;
- parameter hashes and schema-based validation;
- aggregation of duplicate stock and strategy identities across goals;
- explicit non-zero `target_weight` and `capital_share` on builder-created strategy instances;
- reuse of only disabled SHADOW instances;
- one final combined rebalance;
- `BrokerInstrumentSearch`;
- `SchemaParameterForm`;
- migration from the old `GoalStrategySelection`;
- `created_strategy_instance` using `SET_NULL`, so safe strategy deletion does not destroy construction history;
- backend and frontend tests for the current Portfolio Builder flow.

Do not recreate or replace these components.

### 2.2 Useful infrastructure already present

Reuse the existing implementation:

- `Instrument`;
- `BrokerContract`;
- `InstrumentProviderMapping`;
- exact IBKR contract qualification;
- Finnhub provider search and profile verification;
- provider symbol, exchange, currency, ISIN, and FIGI evidence;
- automatic and manual provider verification;
- Celery and Redis;
- Kafka outbox and audit records;
- `PortfolioOptimizationRun`;
- `PortfolioConstructionRun`;
- the current strategy plugin registry;
- SHADOW/PAPER execution controls;
- operation attempts, idempotency keys, throttling, and immutable snapshots.

Do not create a second provider-mapping system.

### 2.3 Missing functionality

The repository still lacks:

- a research/catalog Django application;
- JSON bundle hash and schema validation;
- versioned GICS taxonomy storage;
- issuer-level identity and historical classification;
- a global research universe independent of each user's `PortfolioUniverse`;
- point-in-time membership history;
- research-grade adjusted price and corporate-action data;
- fundamental and event data with availability timestamps;
- a batch feature registry;
- a general research/backtesting engine;
- walk-forward, purge, embargo, cost, capacity, and robustness testing;
- multiple-testing controls;
- candidate scoring and strategy approval;
- cached stock-strategy research results;
- GICS-aware recommendation constraints;
- a recommendation workflow in Portfolio Builder;
- a way to preserve accepted recommendation weights through construction preview.

### 2.4 Current technical constraints

#### Instruments

`Instrument` currently has a free-text `sector` field. It does not contain a versioned four-level GICS hierarchy.

`InstrumentProviderMapping` already provides the provider-mapping lifecycle and must be extended or reused rather than duplicated.

#### Market data

`InstrumentPriceHistory` stores:

- daily OHLC;
- one `adjusted_close`;
- volume;
- provider;
- quality status.

The current Finnhub history path sets `adjusted_close` from the returned close. This is not sufficient for point-in-time split, dividend, total-return, and delisting research.

#### Portfolio optimizer

The existing optimizer:

- supports long-only minimum variance and maximum Sharpe;
- uses historical mean returns;
- uses sample covariance;
- supports per-instrument bounds and turnover;
- does not support GICS sector, industry, sub-industry, strategy-family, or sleeve constraints.

Keep it unchanged for manual Portfolio Builder mode.

Create a research recommendation optimizer separately, or extend shared numerical helpers without changing existing behavior.

#### Strategy runtime

The live `StrategyPlugin` interface is primarily:

- single instrument;
- stream driven;
- one `EvaluationContext`;
- one `StrategyDecision`.

The copied universe contains:

| Scope | Count |
|---|---:|
| Single asset | 30 |
| Cross-sectional | 34 |
| Portfolio | 9 |
| Overlay | 8 |
| Pair or basket | 8 |
| Single-asset or cross-sectional hybrid | 8 |

Therefore, the 97 strategies cannot all be represented honestly as ordinary live `StrategyPlugin` implementations.

#### API security

The repository currently has empty default authentication and permission classes.

Dataset activation, strategy approval, and expensive research administration must initially remain management-command or trusted-operator operations. Do not expose unrestricted public mutation endpoints for them.

---

## 3. Source Bundle

The repository already contains:

```text
Trading_Engine_Stock_Strategy_Universe_JSON/
├── README.md
├── manifest.json
├── gics_taxonomy.json
├── stock_universe.json
├── strategy_universe.json
├── compatibility_rules.json
└── backtest_spec.json
```

Expected bundle values:

| Item | Count |
|---|---:|
| Stocks | 500 |
| GICS sectors represented | 11 |
| GICS industry groups represented | 25 |
| GICS industries represented | 69 |
| GICS sub-industries represented | 127 |
| Full GICS sub-industries | 163 |
| Strategies | 97 |
| Strategy families | 10 |
| Current builder-compatible metadata flags | 81 |
| Research-only long-short definitions | 8 |
| Daily-capable definitions | 95 |

The aggregate strategy parameter grids contain roughly 1,815 template-level parameter combinations before applying stocks, walk-forward windows, regimes, and stress tests. Do not run an uncontrolled Cartesian product.

The stock file is a current snapshot. It must not be treated as historical membership.

---

## 4. Architectural Principles

### 4.1 Catalog everything, execute only approved code

Import all 97 strategies into a research catalog.

Do not create 97 `StrategyDefinition` records.

A research strategy may map to an executable `StrategyDefinition` only after:

1. required datasets are available;
2. every feature has an exact tested implementation;
3. signal and exit semantics are implemented in code;
4. time availability and lag rules are explicit;
5. walk-forward validation passes;
6. costs and capacity checks pass;
7. parameter stability passes;
8. multiple-testing controls pass;
9. a human approval record exists;
10. the implementation is compatible with current long-only Portfolio Builder rules;
11. SHADOW evaluation passes.

### 4.2 Separate strategy roles

Classify imported strategies into operational roles.

| Role | Purpose | Portfolio Builder use |
|---|---|---|
| `SELECTOR` | Ranks or filters stocks across the universe | Candidate selection |
| `EXECUTION` | Produces a long-only exposure series for one stock | Creates `GoalStrategyAssignment` |
| `ALLOCATOR` | Defines portfolio allocation methodology | Recommendation optimizer |
| `OVERLAY` | Scales total risk, cash, or exposure | Recommendation constraints |
| `PAIR_BASKET` | Jointly trades several instruments | Research-only initially |
| `RESEARCH_ONLY` | Missing data, shorting, timing, or engine support | Catalog only |

Initial scope mapping:

| JSON scope | Default role |
|---|---|
| `single_asset` | `EXECUTION` |
| `cross_sectional` | `SELECTOR` |
| `portfolio` | `ALLOCATOR` |
| `overlay` | `OVERLAY` |
| `pair_or_basket` | `PAIR_BASKET` |
| `single_asset_or_cross_sectional` | Explicit implementation variant required |

### 4.3 Preserve existing live goal rules

The bundle contains broad research guidance, but the repository's current rules remain authoritative for live construction.

Current limits:

| Timeframe | Maximum risk |
|---|---:|
| `NOW` | 1 |
| `HURRY` | 2 |
| `FAST` | 3 |
| `BUILD` | 4 |
| `GROW` | 5 |
| `COMPOUND` | 5 |

The recommendation engine must use the intersection of:

- current live goal rules;
- research strategy recommendations;
- approved implementation status;
- current stock eligibility;
- data readiness;
- broker qualification;
- compatibility rules;
- recommendation policy.

Do not overwrite current cash floors, stock caps, risk limits, or horizon labels from the bundle.

### 4.4 Preserve the execution boundary

Research and recommendation code may propose weights.

It must not:

- place orders;
- enable strategy instances;
- bypass Portfolio Builder preview;
- apply a rebalance automatically;
- create LIVE strategies;
- create separate goal broker portfolios;
- create separate goal cash or financial ledgers.

---

## 5. Target Architecture

```text
Copied JSON bundle
        ↓
Hash + JSON Schema validation
        ↓
Versioned research catalog
  ├── GICS taxonomy
  ├── issuer and universe metadata
  ├── strategy definitions
  ├── compatibility rules
  └── backtest protocol
        ↓
Instrument and provider mapping
        ↓
Point-in-time research data
        ↓
Feature readiness
        ↓
Offline strategy experiments
        ↓
Robustness, cost and multiple-testing controls
        ↓
Approved candidate scores
        ↓
Goal timeframe + risk request
        ↓
Sleeve-level recommendation optimizer
        ↓
Immutable recommendation snapshot
        ↓
User acceptance
        ↓
Existing GoalInstrumentSelection
Existing GoalStrategyAssignment
Accepted recommendation weight source
        ↓
Existing construction preview
        ↓
Existing one combined SHADOW/PAPER rebalance
```

---

## 6. New Django Application

Create:

```text
Backend/apps/research/
```

Suggested structure:

```text
apps/research/
├── admin.py
├── apps.py
├── models.py
├── enums.py
├── schemas/
│   ├── manifest.schema.json
│   ├── gics_taxonomy.schema.json
│   ├── stock_universe.schema.json
│   ├── strategy_universe.schema.json
│   ├── compatibility_rules.schema.json
│   └── backtest_spec.schema.json
├── services/
│   ├── bundle_validation.py
│   ├── bundle_import.py
│   ├── classification.py
│   ├── universe_mapping.py
│   ├── data_readiness.py
│   ├── eligibility.py
│   ├── features.py
│   ├── experiments.py
│   ├── scoring.py
│   ├── promotion.py
│   ├── optimizer.py
│   ├── recommendations.py
│   └── acceptance.py
├── engines/
│   ├── base.py
│   ├── single_asset.py
│   ├── cross_sectional.py
│   ├── allocator.py
│   ├── overlay.py
│   ├── event.py
│   └── pair_basket.py
├── implementations/
│   └── exact research strategy implementations
├── management/commands/
│   ├── validate_research_bundle.py
│   ├── import_research_bundle.py
│   ├── map_research_universe.py
│   ├── refresh_research_data.py
│   ├── calculate_research_eligibility.py
│   ├── run_research_experiments.py
│   ├── score_research_candidates.py
│   └── promote_research_strategy.py
├── tasks.py
├── views.py
├── urls.py
└── migrations/
```

Add `apps.research` to `INSTALLED_APPS`.

---

## 7. Data Model

### 7.1 Bundle versioning

#### `ResearchDatasetVersion`

Fields:

- `bundle_name`;
- `version`;
- `snapshot_date`;
- `source_path`;
- `status`: `STAGED`, `VALIDATED`, `ACTIVE`, `RETIRED`, `FAILED`;
- `manifest_hash`;
- `file_hashes`;
- `source_metadata`;
- `validation_report`;
- `imported_at`;
- `activated_at`;
- `retired_at`.

Rules:

- one active version per bundle name;
- activation is atomic;
- identical manifest hash is idempotent;
- different content under the same version is rejected;
- failed imports leave no partially active version.

#### `BacktestProtocolVersion`

Fields:

- `protocol_id`;
- `dataset_version`;
- `configuration`;
- `configuration_hash`;
- `active`;
- timestamps.

#### `CompatibilityRuleSet`

Fields:

- `dataset_version`;
- `configuration`;
- `configuration_hash`;
- `active`.

---

### 7.2 Issuer and classification

#### `Issuer`

Add to `apps.instruments` because issuer identity is broader than research.

Fields:

- `cik`, unique and nullable only for unsupported instruments;
- `legal_name`;
- `display_name`;
- `headquarters`;
- `founded`;
- timestamps.

Add nullable `issuer` to `Instrument`.

Do not use ticker as issuer identity.

#### `GICSTaxonomyNode`

Fields:

- `dataset_version`;
- `level`: `SECTOR`, `INDUSTRY_GROUP`, `INDUSTRY`, `SUB_INDUSTRY`;
- `code`;
- `name`;
- `parent`;
- `path`;
- `active`.

Constraints:

- unique `(dataset_version, code)`;
- valid parent level;
- complete path from sector to the node.

#### `InstrumentClassification`

Fields:

- `instrument`, nullable when only issuer metadata exists;
- `issuer`;
- `taxonomy_version`;
- `sub_industry_node`;
- `effective_from`;
- `effective_to`;
- `is_current`;
- `source_dataset_version`.

The parent hierarchy supplies sector, industry group, and industry.

Historical research must query classification effective on the decision date.

---

### 7.3 Research universe

#### `ResearchUniverse`

Fields:

- `key`;
- `name`;
- `description`;
- `dataset_version`;
- `membership_type`: `CURRENT_SNAPSHOT`, `POINT_IN_TIME`;
- `active`;
- timestamps.

#### `ResearchUniverseMember`

Fields:

- `universe`;
- `issuer`;
- `instrument`, nullable;
- `source_symbol`;
- `security_name`;
- `currency`;
- `exchange_hint`;
- `membership_start`;
- `membership_end`;
- `membership_status`;
- `research_eligibility_configuration`;
- `risk_timeframe_profile`;
- `mapping_status`;
- `mapping_notes`;
- `active`.

Mapping statuses:

- `METADATA_ONLY`;
- `INSTRUMENT_MAPPED`;
- `PROVIDER_VERIFIED`;
- `RESEARCH_DATA_READY`;
- `BROKER_QUALIFIED`;
- `REJECTED`;
- `RETIRED`.

Do not create fake `BrokerContract` rows while importing the 500-stock file.

#### `InstrumentEligibilitySnapshot`

Fields:

- `universe_member`;
- `as_of_date`;
- `price`;
- `median_dollar_volume_20d`;
- `history_days`;
- `trading_days_252d`;
- `realized_volatility`;
- `maximum_drawdown`;
- `data_quality_status`;
- `research_eligible`;
- `builder_eligible`;
- `rejection_reasons`;
- `metrics`.

Unique `(universe_member, as_of_date)`.

---

### 7.4 Research strategy catalog

#### `ResearchStrategyDefinition`

Preserve the supplied JSON fields:

- `research_id`;
- `dataset_version`;
- `name`;
- `family`;
- `scope`;
- `role`;
- `description`;
- `research_hypothesis`;
- `production_status`;
- `engine_compatibility`;
- `supported_directions`;
- `supported_frequencies`;
- `typical_holding_period`;
- `required_data`;
- `features`;
- `signal_logic`;
- `parameter_grid`;
- `eligibility_filters`;
- `portfolio_construction`;
- `risk_controls`;
- `recommended_risk_levels`;
- `recommended_goal_timeframes`;
- `required_metrics`;
- `known_failure_modes`;
- `configuration_hash`;
- `active`.

Unique `(dataset_version, research_id)`.

#### `ResearchFeatureDefinition`

Fields:

- `key`;
- `category`;
- `description`;
- `formula`;
- `batch_implementation_path`, nullable;
- `stream_input_name`, nullable;
- `supported_frequencies`;
- `required_datasets`;
- `availability_lag`;
- `status`: `DECLARED`, `IMPLEMENTED`, `VALIDATED`, `BLOCKED`;
- timestamps.

#### `ResearchStrategyFeatureRequirement`

Join strategy to required features.

#### `ResearchStrategyImplementation`

Fields:

- `research_strategy`;
- `implementation_path`;
- `implementation_version`;
- `implementation_hash`;
- `role`;
- `exact_semantic_match`;
- `supported_frequency`;
- `supported_direction`;
- `status`: `DRAFT`, `VALIDATED`, `APPROVED`, `RETIRED`;
- `executable_strategy_definition`, nullable;
- `default_parameters`;
- `approval_record`;
- timestamps.

A mapping to `StrategyDefinition` is allowed only when `exact_semantic_match=true`.

#### `ResearchStrategyReadiness`

Fields:

- `research_strategy`;
- `as_of_date`;
- `data_ready`;
- `features_ready`;
- `implementation_ready`;
- `backtest_ready`;
- `approved`;
- `builder_ready`;
- `blocking_reasons`.

---

### 7.5 Research data

Keep operational market data stable.

Add research-grade tables instead of silently changing the meaning of existing data.

#### `ResearchDailyBar`

Fields:

- `instrument`;
- `trading_date`;
- raw OHLC;
- adjusted OHLC;
- raw close;
- adjusted close;
- total-return close;
- volume;
- cash dividend;
- split factor;
- adjustment factor;
- provider;
- provider_timestamp;
- revision_timestamp;
- data_version;
- quality_status.

#### `ResearchCorporateAction`

Support:

- dividend;
- split;
- symbol change;
- merger;
- spin-off;
- delisting;
- cash proceeds.

#### `ResearchFundamentalFact`

Fields must include:

- issuer;
- metric;
- period start/end;
- filing timestamp;
- public availability timestamp;
- value;
- units;
- original value;
- revision version.

A value must never be visible before its availability timestamp.

#### `ResearchEvent`

Fields:

- issuer/instrument;
- event type;
- announced timestamp;
- effective timestamp;
- timezone;
- payload;
- quality status.

Unknown announcement timing means next-session availability.

---

### 7.6 Experiments and artifacts

#### `ResearchExperiment`

Fields:

- strategy;
- universe;
- protocol;
- dataset version;
- experiment type;
- parameter budget;
- request hash;
- idempotency key;
- status;
- started/completed timestamps;
- error.

#### `ResearchTrial`

Fields:

- experiment;
- instrument, nullable;
- peer group or basket reference, nullable;
- parameters;
- parameter hash;
- window configuration;
- status;
- summary metrics;
- validation metrics;
- rejection reasons;
- artifact URI.

Do not store complete return and trade series as large JSON blobs in PostgreSQL.

Create an `ArtifactStore` interface:

- filesystem backend for local development;
- S3-compatible backend later;
- Parquet for returns, trades, features, and attribution.

#### `ResearchCandidateScore`

Fields:

- strategy;
- instrument, nullable;
- candidate type;
- goal timeframe;
- risk level;
- as-of date;
- score;
- eligible;
- hard-rejection reasons;
- best parameters;
- metrics;
- regime metrics;
- cost metrics;
- stability metrics;
- capacity metrics;
- protocol version;
- dataset version;
- expires at.

Indexes:

- `(goal_timeframe, risk_level, eligible, score desc)`;
- `(instrument, goal_timeframe, risk_level)`;
- `(strategy, as_of_date)`.

---

### 7.7 Recommendations

#### `GoalRecommendationPolicy`

Fields/configuration:

- minimum candidate score;
- maximum candidate age;
- number of stocks;
- minimum sectors;
- sector cap;
- industry cap;
- sub-industry cap;
- per-stock cap;
- strategy-family cap;
- maximum turnover;
- minimum cash;
- target volatility;
- maximum expected drawdown;
- minimum liquidity;
- approved candidate roles.

Build policies from current repository rules and explicit new defaults.

#### `GoalRecommendationRun`

Fields:

- `goal_allocation`;
- `requested_plan_version`;
- `policy`;
- `dataset_version`;
- `protocol_version`;
- `as_of_date`;
- `status`;
- `idempotency_key`;
- `request_hash`;
- `input_snapshot`;
- `candidate_snapshot`;
- `optimizer_snapshot`;
- `stress_test_snapshot`;
- `metrics`;
- `warnings`;
- `expires_at`;
- `accepted_at`;
- timestamps.

#### `GoalRecommendationSleeve`

A sleeve is one stock plus one executable strategy.

Fields:

- `recommendation_run`;
- `instrument`;
- `universe_member`;
- `research_strategy`;
- `execution_strategy_definition`;
- `execution_timeframe`;
- `parameters`;
- `sleeve_weight`;
- `stock_weight`;
- `strategy_share`;
- `candidate_score`;
- `expected_return`;
- `expected_volatility`;
- `expected_drawdown`;
- `cost_metrics`;
- `rationale`;
- `rank`.

For stock `i` and strategy `k`:

```text
x(i,k) = recommended sleeve weight
stock_weight(i) = sum over k of x(i,k)
strategy_share(i,k) = x(i,k) / stock_weight(i)
```

The current `GoalStrategyAssignment` model can represent these shares exactly.

#### `GoalRecommendationAcceptance`

Fields:

- recommendation run;
- goal;
- accepted plan version;
- created/updated instrument selections;
- created/updated strategy assignments;
- accepted by;
- accepted at;
- change summary.

---

## 8. Preserve Recommendation Weights Through Construction

Simply adding recommended stocks and strategies to the current builder is not enough because the current builder would run Markowitz again on raw stock returns and replace the recommendation weights.

Add an explicit goal construction source.

### 8.1 `PortfolioGoalAllocation` changes

Add:

- `construction_source`: `MANUAL_OPTIMIZER` or `ACCEPTED_RECOMMENDATION`;
- `accepted_recommendation_run`, nullable and protected/set-null according to deletion requirements.

Default existing rows to `MANUAL_OPTIMIZER`.

### 8.2 Manual mode

`MANUAL_OPTIMIZER` must behave exactly as it does now.

No regression is allowed.

### 8.3 Recommendation mode

For `ACCEPTED_RECOMMENDATION`:

1. snapshot the accepted immutable recommendation;
2. load its local stock and cash weights;
3. validate that stock plus cash equals 100%;
4. validate current maximum stock weight;
5. validate minimum cash;
6. validate GICS caps;
7. validate every instrument is still active and tradable;
8. validate every accepted execution strategy is still approved;
9. validate strategy shares total 100% per stock;
10. block apply when the recommendation has expired or materially stale data is detected;
11. use the accepted fixed local weights instead of calling the current Markowitz optimizer;
12. preserve all existing final aggregation, target creation, preview, rebalance, and SHADOW instance logic.

### 8.4 Manual edits after acceptance

Any manual change to:

- goal risk;
- goal timeframe;
- selected instruments;
- weight bounds;
- strategy assignments;
- strategy parameters;
- strategy shares;

must either:

- explicitly detach the accepted recommendation and return the goal to `MANUAL_OPTIMIZER`; or
- be rejected until the operator chooses `Detach recommendation`.

Never silently keep a recommendation label after its contents were changed.

---

## 9. Bundle Validation and Import

### 9.1 Validation sequence

1. locate `Trading_Engine_Stock_Strategy_Universe_JSON/manifest.json`;
2. verify all required files exist;
3. verify SHA-256 hashes;
4. validate all JSON against repository JSON Schemas;
5. verify exact counts;
6. verify GICS parent-child integrity;
7. verify every stock sub-industry exists;
8. verify unique strategy IDs;
9. verify unique representative-company rules;
10. verify supported enums;
11. normalize frequencies;
12. calculate strategy-role mapping;
13. record data and engine blockers;
14. import inside one transaction;
15. activate only after success.

Normalize:

| Source | Engine |
|---|---|
| `1D` | `1d` |
| `1H` | `1h` |
| `15m` | `15m` |
| `5m` | `5m` |
| `1m` | `1m` |

Unknown values fail validation.

### 9.2 Commands

```bash
python manage.py validate_research_bundle \
  Trading_Engine_Stock_Strategy_Universe_JSON

python manage.py import_research_bundle \
  Trading_Engine_Stock_Strategy_Universe_JSON \
  --activate
```

Requirements:

- idempotent;
- safe to rerun;
- records audit events;
- no broker calls during import;
- no automatic executable strategy creation;
- no large JSON embedded in migrations.

---

## 10. Stock and GICS Integration

### 10.1 Import behavior

For each stock:

1. upsert issuer by CIK;
2. create a `ResearchUniverseMember`;
3. import the current GICS path;
4. attempt deterministic link to an existing `Instrument`;
5. create an unqualified canonical `Instrument` only when exact symbol, asset class, exchange hint, and currency are unambiguous;
6. do not create a fake broker contract;
7. create or reuse `InstrumentProviderMapping`;
8. leave unresolved cases for operator review.

### 10.2 Mapping priority

1. existing issuer-linked instrument;
2. existing broker contract with exact local symbol/currency;
3. exact symbol, currency, asset class, and primary exchange;
4. existing verified `InstrumentProviderMapping`;
5. operator-reviewed IBKR selection;
6. unresolved.

Never merge instruments only by company name.

### 10.3 Broker qualification

For actionable recommendations:

- require exact IBKR qualification;
- process in rate-limited batches;
- record ambiguity and errors;
- never guess an exchange;
- never permit a metadata-only member to be accepted into a goal.

Research can run without broker qualification when reliable provider mapping exists.

### 10.4 Dynamic eligibility

Calculate daily eligibility from:

- active membership;
- price;
- median dollar volume;
- trading-session count;
- adjusted-history length;
- stale data;
- unresolved corporate actions;
- volatility;
- drawdown;
- strategy data requirements;
- GICS rules;
- broker status.

Static JSON tags are broad priors, not final suitability.

---

## 11. Research Data Pipeline

### 11.1 Reuse existing provider infrastructure

Reuse:

- provider clients;
- provider capabilities;
- provider error taxonomy;
- `InstrumentProviderMapping`;
- Finnhub mapping verification;
- Celery and provider throttling.

Do not use the operational fallback flag as the only switch for research data.

Add separate settings:

```text
RESEARCH_ENABLED
RESEARCH_BUNDLE_PATH
RESEARCH_ARTIFACT_ROOT
RESEARCH_MAX_PARALLEL_TASKS
RESEARCH_DAILY_PROVIDER
RESEARCH_SCORE_MAX_AGE_DAYS
RESEARCH_RECOMMENDATION_MAX_AGE_DAYS
```

### 11.2 Required task flow

```text
membership refresh
→ provider mapping
→ research data refresh
→ data-quality checks
→ corporate-action reconciliation
→ eligibility snapshot
→ feature calculation
→ experiments
→ scoring
→ recommendation cache
```

### 11.3 Celery queues

Use dedicated queues:

- `research_data`;
- `research_features`;
- `research_backtests`;
- `research_scoring`;
- `research_recommendations`.

Use:

- Redis locks;
- idempotency keys;
- chunked batches;
- task retry policies;
- provider rate limits;
- bounded groups/chords.

Do not launch hundreds of thousands of Celery tasks at once.

---

## 12. Feature Registry

Build batch features independently from live streaming indicators.

Each feature must define:

- exact formula;
- input columns;
- lookback;
- warm-up;
- publication or availability lag;
- NaN policy;
- corporate-action policy;
- implementation path;
- version;
- deterministic tests;
- optional equivalent live stream input.

A strategy is not backtest-ready until every feature is `VALIDATED`.

Do not assume that an existing live indicator is semantically identical to the research feature.

Examples requiring exact parity checks:

- shifted Donchian channels;
- skipped-month momentum;
- residual momentum;
- sector-relative momentum;
- filing-lagged valuation;
- dividend yield with historical shares;
- ATR stops;
- earnings timing;
- peer residual z-scores.

---

## 13. Research Strategy Interfaces

Create explicit interfaces.

### 13.1 Single asset

Input:

- one instrument's point-in-time data;
- parameters;
- protocol context.

Output:

- desired exposure series;
- trades;
- diagnostics.

### 13.2 Cross-sectional selector

Input:

- dated eligible-universe panel;
- point-in-time GICS;
- parameters.

Output:

- rankings, scores, or selection weights by date.

### 13.3 Allocator

Input:

- candidate sleeve returns;
- current holdings;
- constraints;
- parameters.

Output:

- portfolio sleeve weights.

### 13.4 Overlay

Input:

- base sleeve weights;
- market/risk state.

Output:

- bounded exposure scalar or adjusted constraints.

### 13.5 Event

Input:

- exact timestamped events;
- point-in-time market data.

Output:

- eligible signals only after event availability.

### 13.6 Pair/basket

Research-only initially.

Do not map pair/basket strategies to one single-instrument `StrategyInstance`.

---

## 14. Strategy Implementation Waves

### Wave 0: Existing executable strategies

Create exact research adapters for the current five plugins:

- RSI Mean Reversion;
- SMA Crossover;
- Donchian Breakout;
- Volatility-Target Momentum;
- Fixed-Weight Rebalance.

Do not label them as exact matches to a JSON strategy until golden-vector parity passes.

### Wave 1: Daily long-only single-asset strategies

Prioritize:

- buy-and-hold baseline;
- SMA and EMA trends;
- price versus long moving average;
- Donchian variants;
- MACD trend;
- daily RSI variants;
- Bollinger and moving-average reversion;
- time-series momentum;
- 52-week high;
- single-asset volatility target;
- ATR sizing;
- drawdown control.

### Wave 2: Cross-sectional selectors

Implement:

- cross-sectional momentum;
- residual and sector-relative momentum;
- short-term reversal;
- low volatility;
- quality;
- value;
- profitability;
- investment;
- multi-factor combinations.

### Wave 3: Portfolio allocators and overlays

Implement:

- equal weight;
- sector-neutral equal weight;
- inverse volatility;
- risk parity;
- minimum variance;
- maximum diversification;
- hierarchical risk parity;
- minimum CVaR;
- portfolio volatility target;
- correlation shock;
- regime and liquidity overlays.

### Wave 4: Fundamentals, income, and events

Only after point-in-time datasets are complete.

### Wave 5: Intraday, pair/basket, and long-short

Keep research-only until the engine supports:

- multi-instrument state;
- short exposure;
- borrow cost and availability;
- intraday bars and quotes;
- exact event timestamps;
- portfolio-level target emission.

---

## 15. Backtesting Protocol

Implement the supplied `backtest_spec.json` as a versioned protocol.

### 15.1 Point-in-time requirements

- point-in-time universe membership;
- delisted securities and delisting returns;
- historical GICS;
- filing/publication timestamps;
- exact event availability;
- no current-snapshot survivorship claims.

The current 500-stock snapshot may be used for:

- forward research;
- system testing;
- prospective candidate generation.

It may not be used to claim unbiased historical performance.

### 15.2 Execution

- features through bar `t` may trade no earlier than `t+1`;
- use configurable next-open or next-session VWAP fill;
- include commission;
- include spread;
- include square-root market impact;
- include cost stress at 5, 10, 25, and 50 bps round trip;
- include borrow cost for research-only shorts;
- enforce liquidity and participation limits.

### 15.3 Walk-forward validation

Support:

- 3-, 5-, and 10-year training windows where available;
- 6- and 12-month validation;
- 6- and 12-month test windows;
- rolling and expanding windows;
- at least five independent test windows;
- purging;
- embargo;
- untouched final holdout.

### 15.4 Robustness

Implement:

- neighboring-parameter stability;
- execution delay;
- missing-data stress;
- bootstrap confidence intervals;
- subperiod consistency;
- leave-one-sector-out;
- leave-one-year-out;
- regime slices;
- GICS slices;
- liquidity and volatility deciles.

### 15.5 Multiple testing

Record every trial.

Implement:

- deflated Sharpe ratio;
- probability of backtest overfitting;
- false-discovery-rate control;
- untouched holdout protection.

### 15.6 Parameter budget

Do not run every full grid for every stock automatically.

For each strategy:

1. calculate theoretical grid size;
2. retain canonical baseline parameters;
3. apply compatibility and data pruning;
4. set a deterministic trial budget;
5. sample oversized grids reproducibly;
6. promote only stable parameter neighborhoods.

---

## 16. Candidate Scoring

Apply hard rejections before scoring.

Hard rejections include:

- data-quality failure;
- leakage or timestamp ambiguity;
- negative net result under high-cost scenario;
- drawdown above profile;
- insufficient trades;
- unstable parameter neighborhood;
- liquidity/capacity failure;
- excessive dependence on one subperiod.

Use the supplied normalized score:

| Component | Weight |
|---|---:|
| Out-of-sample Sharpe | 20% |
| Calmar | 15% |
| Drawdown fit | 15% |
| Regime consistency | 15% |
| Parameter stability | 10% |
| Cost resilience | 10% |
| Turnover efficiency | 5% |
| Capacity | 5% |
| Diversification contribution | 5% |

Minimum candidate score: `65`.

Normalize within comparable cohorts:

- role;
- frequency;
- goal timeframe;
- risk level;
- long-only versus research-only.

Do not compare unrelated strategies using raw Sharpe alone.

---

## 17. Recommendation Engine

### 17.1 Offline inputs

Precompute and cache:

- eligible stocks;
- selector scores;
- executable stock-strategy sleeve returns;
- strategy parameters;
- cost metrics;
- covariance;
- GICS metadata;
- stress scenarios;
- capacity;
- candidate expiry.

### 17.2 Online request flow

```text
goal timeframe + risk
→ current live policy
→ latest approved candidates
→ current dynamic stock eligibility
→ broker-qualified actionable set
→ selector filtering
→ sleeve candidate construction
→ constrained sleeve optimization
→ overlays and stress tests
→ explanation
→ immutable recommendation
```

Target user-facing latency: `3-15 seconds`.

### 17.3 Sleeve optimization

Optimize sleeve weights `x(i,k)`.

Example objective:

```text
maximize:
    expected_net_return
    - risk_aversion × portfolio_variance
    - cost_penalty
    - turnover_penalty
    - concentration_penalty
    - instability_penalty
```

Constraints:

- sleeve weights non-negative;
- stock plus cash equals 100%;
- current repository cash floor;
- current repository stock cap;
- sector cap;
- industry cap;
- sub-industry cap;
- strategy-family cap;
- total strategy cap;
- turnover cap;
- liquidity and capacity;
- approved long-only execution strategies only.

The recommendation optimizer must not call the existing manual Markowitz path and then claim GICS-aware strategy optimization occurred.

### 17.4 Selector, allocator, execution, and overlay behavior

- selectors rank or filter stocks;
- execution strategies produce sleeve return streams and assignments;
- allocator strategies select or configure the optimization method;
- overlays adjust exposure or risk constraints;
- pair/basket strategies remain outside actionable recommendations initially.

### 17.5 Recommendation output

Return:

- stock;
- GICS hierarchy;
- stock weight;
- execution strategy;
- strategy share;
- parameters;
- candidate score;
- expected return;
- volatility;
- expected drawdown;
- cost sensitivity;
- regime weaknesses;
- inclusion rationale;
- rejected close alternatives;
- data version;
- protocol version;
- expiry.

---

## 18. Recommendation Acceptance

Acceptance must:

1. lock the recommendation, goal, and plan;
2. verify plan version has not changed;
3. verify the recommendation has not expired;
4. recheck broker qualification;
5. recheck strategy approval;
6. create or update `GoalInstrumentSelection`;
7. disable goal stocks not present in the accepted recommendation;
8. create or update exact `GoalStrategyAssignment` identities;
9. disable replaced assignments;
10. set exact strategy shares;
11. set `construction_source=ACCEPTED_RECOMMENDATION`;
12. link the accepted recommendation to the goal;
13. bump the plan version;
14. record an audit event and acceptance record;
15. return the operator to normal Portfolio Builder preview.

Acceptance must not:

- create strategy instances;
- preview automatically;
- apply automatically;
- submit orders;
- enable strategies.

---

## 19. API Plan

### Read-only research APIs

```text
GET /api/v1/research/dataset-versions/
GET /api/v1/research/universes/
GET /api/v1/research/universes/{id}/members/
GET /api/v1/research/strategies/
GET /api/v1/research/strategies/{research_id}/
GET /api/v1/research/readiness/
GET /api/v1/research/candidate-scores/
GET /api/v1/research/experiments/{id}/
```

Use pagination and filters.

### Goal recommendation APIs

```text
POST /api/v1/portfolio-construction/goals/{goal_id}/recommendations/
GET  /api/v1/portfolio-construction/recommendations/{run_id}/
POST /api/v1/portfolio-construction/recommendations/{run_id}/accept/
POST /api/v1/portfolio-construction/goals/{goal_id}/detach-recommendation/
```

Requirements:

- idempotency key;
- request hash;
- asynchronous Celery task;
- polling status;
- plan-version conflict detection;
- immutable completed result;
- audit record;
- throttling;
- no execution side effect.

### Administrative actions

Keep these as management commands initially:

- bundle activation;
- strategy approval;
- strategy promotion;
- full experiment scheduling;
- provider overrides.

---

## 20. Frontend Plan

### 20.1 Research Universe page

Show:

- active dataset version;
- manifest status;
- counts;
- GICS coverage;
- stock mapping status;
- provider verification;
- broker qualification;
- data readiness;
- strategy family/scope;
- implementation status;
- approval status;
- recent experiments and errors.

### 20.2 Portfolio Builder integration

For each non-`NOW` goal, add:

- `Generate recommendation`;
- recommendation status;
- recommended stocks and GICS allocation;
- recommended strategy sleeves;
- expected metrics;
- warnings;
- `Accept recommendation`;
- `Regenerate`;
- `Detach recommendation`;
- `Keep manual mode`.

### 20.3 Review behavior

Allow the operator to inspect:

- stock and strategy rationale;
- cost stress;
- regime weakness;
- data version;
- expiry;
- alternatives.

Do not permit silent editing of an accepted recommendation.

The operator must detach it first or generate a new recommendation.

### 20.4 Preview

The current preview must clearly display:

- construction source;
- accepted recommendation ID;
- fixed recommended local weights;
- stock contributions;
- strategy shares;
- strategy-controlled weights;
- final combined stock target;
- planned rebalance trades;
- expiration or staleness warnings.

---

## 21. Scheduling and Performance

Suggested schedule:

| Task | Schedule |
|---|---|
| Bundle and taxonomy check | Daily |
| Membership refresh | Daily |
| Research daily bars | After market close |
| Corporate actions | After market close |
| Eligibility snapshots | After data refresh |
| Feature calculation | After eligibility |
| Incremental single-asset experiments | Nightly |
| Cross-sectional and allocator research | Weekly |
| Full protocol rerun | Monthly or new dataset |
| Candidate scoring | After successful experiments |
| Recommendation cache warm-up | After scoring |

Performance requirements:

- no research work in web workers;
- bounded Celery concurrency;
- indexed candidate lookup;
- paginated 500-stock APIs;
- immutable cached results;
- recommendation response within 3-15 seconds when research is current;
- no unbounded JSON response or database query;
- no unbounded Celery fan-out.

---

## 22. Strategy Promotion Workflow

```text
IMPORTED
→ DATA_READY
→ FEATURE_READY
→ IMPLEMENTED
→ BACKTESTED
→ APPROVED
→ SHADOW_VALIDATED
→ BUILDER_ELIGIBLE
→ RETIRED
```

Promotion requires:

1. exact implementation;
2. deterministic golden-vector tests;
3. complete data;
4. successful protocol run;
5. score at least 65;
6. no hard rejection;
7. stable neighboring parameters;
8. acceptable high-cost result;
9. human approval;
10. long-only compatibility;
11. exact `StrategyDefinition` mapping;
12. valid `StrategyConstructionProfile`;
13. successful SHADOW evaluation.

New executable definitions must begin disabled or non-user-selectable until approval is complete.

---

## 23. File-Level Change Map

### Backend

| Area | Changes |
|---|---|
| `Backend/config/settings.py` | Install research app, flags, queues, schedules |
| `Backend/config/urls.py` | Research and recommendation endpoints |
| `Backend/apps/instruments/models.py` | Add issuer link; reuse provider mappings |
| `Backend/apps/instruments/services.py` | Universe mapping and qualification helpers |
| `Backend/apps/market_data/` | Reuse provider clients; keep operational behavior stable |
| `Backend/apps/research/` | New catalog, data, backtest, scoring, optimizer, recommendation app |
| `Backend/apps/portfolio_construction/models.py` | Construction source and accepted recommendation link |
| `Backend/apps/portfolio_construction/services.py` | Preserve accepted fixed weights in recommendation mode |
| `Backend/apps/portfolio_construction/views.py` | Recommendation generation, acceptance, detach |
| `Backend/apps/portfolio_optimization/` | Do not change manual behavior; share safe numerical helpers only |
| `Backend/apps/strategies/` | Add only exact approved executable implementations |
| `Backend/requirements.txt` | Add research dependencies such as pandas and pyarrow |
| `Backend/tests/` | Research, recommendation, data leakage, and regression tests |

### Frontend

| Area | Changes |
|---|---|
| `Frontend/src/api/types.ts` | Research and recommendation types |
| `Frontend/src/api/queries.ts` | Research and recommendation queries |
| `Frontend/src/features/research/` | New research screens |
| `Frontend/src/features/portfolio-builder/PortfolioBuilderPage.tsx` | Generate, review, accept, detach |
| frontend tests | Recommendation and preservation flows |

### Documentation

Replace the stale root `implementation_plan.md` with this plan.

Update:

- `README.md`;
- `docs/PORTFOLIO_BUILDER.md`;
- `docs/PORTFOLIO_OPTIMIZATION.md`;
- add `docs/RESEARCH_UNIVERSE.md`;
- add `docs/BACKTESTING_PROTOCOL.md`;
- add `docs/STRATEGY_PROMOTION.md`;
- add `docs/RECOMMENDATION_ENGINE.md`.

---

## 24. Implementation Phases

### Phase 0: Baseline and completed-work protection

- run all current tests;
- record pre-existing failures;
- add regression tests proving the completed stock/strategy builder architecture remains unchanged;
- remove the stale old implementation plan;
- validate that the copied JSON files match the manifest.

### Phase 1: Research catalog foundation

- create `apps.research`;
- add dataset, taxonomy, universe, strategy, protocol, and compatibility models;
- add `Issuer`;
- add migrations;
- add admin views;
- add JSON Schemas.

### Phase 2: Atomic bundle importer

- implement validation command;
- implement import command;
- import exactly 500 stocks;
- import exactly 97 strategy definitions;
- import full GICS taxonomy;
- activate one version atomically;
- add hash, count, idempotency, and rollback tests.

### Phase 3: Instrument and provider mapping

- map members to existing instruments;
- reuse `InstrumentProviderMapping`;
- add operator review;
- add controlled exact broker qualification;
- separate research readiness from builder eligibility.

### Phase 4: Research data and eligibility

- add research daily bars and corporate actions;
- add point-in-time data interfaces;
- add data-quality checks;
- add global research-universe refresh;
- add eligibility snapshots.

### Phase 5: Feature registry and Wave 0

- add batch feature registry;
- implement exact adapters for the five current plugins;
- add golden-vector and lag tests;
- keep mappings unapproved until parity passes.

### Phase 6: Daily backtest engine

- implement single-asset engine;
- implement walk-forward windows;
- implement costs;
- implement purging and embargo;
- implement artifacts;
- implement robustness tests;
- implement multiple-testing records.

### Phase 7: Candidate scoring and promotion

- implement hard rejections;
- implement 0-100 score;
- implement readiness and approval;
- produce first approved daily candidate set.

### Phase 8: Research optimizer and recommendations

- implement selectors, sleeves, GICS constraints, overlays, and stress tests;
- generate immutable recommendation snapshots;
- target 3-15 second online latency.

### Phase 9: Accepted recommendation construction mode

- add construction source;
- accept recommendation into existing stock and assignment rows;
- preserve exact recommended local weights;
- add detach behavior;
- keep existing preview and apply mandatory.

### Phase 10: Frontend

- add research screens;
- add recommendation generation;
- add review, accept, regenerate, and detach;
- show source, versions, metrics, and warnings.

### Phase 11: Wider strategy waves

- Wave 1 daily single-asset;
- Wave 2 cross-sectional;
- Wave 3 allocators/overlays;
- Wave 4 fundamentals/events;
- Wave 5 pair/basket/intraday only after required architecture exists.

### Phase 12: Scheduling, performance, and documentation

- add Celery queues and schedules;
- benchmark refresh and recommendation latency;
- enforce expiry;
- update documentation;
- remove dead experimental code;
- run full verification.

---

## 25. Testing Plan

### 25.1 Bundle tests

- missing file;
- bad hash;
- wrong count;
- duplicate strategy ID;
- invalid GICS parent;
- unknown stock sub-industry;
- unknown frequency;
- same import idempotent;
- changed data under same version rejected;
- failed import not activated.

### 25.2 Mapping tests

- CIK issuer identity;
- share-class handling;
- existing instrument match;
- existing provider mapping reuse;
- ambiguous ticker not guessed;
- unqualified stock not builder eligible;
- exact broker qualification;
- provider identity change resets verification.

### 25.3 Data tests

- split adjustment;
- dividend adjustment;
- delisting return;
- duplicate bars;
- missing sessions;
- stale data;
- revision handling;
- filing availability;
- event availability;
- no future leakage.

### 25.4 Feature and strategy tests

- deterministic feature values;
- warm-up;
- lag;
- NaN policy;
- corporate-action handling;
- exact strategy semantics;
- existing plugin parity;
- unsupported data blocks readiness;
- pair/basket not mapped to single-asset runtime.

### 25.5 Backtest tests

- next-bar execution;
- commission;
- spread;
- market impact;
- cost stress;
- walk-forward windows;
- purge;
- embargo;
- final holdout;
- parameter budget;
- deterministic rerun;
- bootstrap;
- regime slices;
- multiple-testing controls;
- hard rejection;
- score calculation.

### 25.6 Recommendation tests

- `NOW` returns cash only;
- current live timeframe/risk rules override broader bundle metadata;
- only approved, current candidates used;
- only broker-qualified stocks actionable;
- sector/industry/sub-industry caps;
- stock cap;
- cash floor;
- strategy-family cap;
- strategy shares total 100%;
- sleeve weights aggregate exactly to stock weights;
- recommendation total plus cash equals 100%;
- expired recommendation blocked;
- plan-version conflict blocked;
- acceptance is idempotent;
- acceptance creates no strategy instance;
- acceptance creates no rebalance;
- accepted weights survive construction preview unchanged;
- manual mode behaves exactly as before;
- manual edits require detach;
- apply still creates one combined rebalance;
- created strategy instances remain disabled SHADOW.

### 25.7 Frontend tests

- generate recommendation;
- poll status;
- show GICS and strategy sleeves;
- show warnings and versions;
- accept recommendation;
- detach recommendation;
- preserve manual mode;
- preview exact accepted weights;
- no automatic apply.

### 25.8 Required verification

```bash
cd Backend && pytest
cd ../IB_gateway && pytest
cd ../Frontend && npm install && npm test && npm run build
cd .. && ./.venv/Scripts/python -m pytest streaming/flink/tests
docker compose config --quiet
```

Also run:

```bash
cd Backend

python manage.py check
python manage.py makemigrations --check

python manage.py validate_research_bundle \
  ../Trading_Engine_Stock_Strategy_Universe_JSON

python manage.py import_research_bundle \
  ../Trading_Engine_Stock_Strategy_Universe_JSON \
  --activate
```

Run repository smoke tests when the environment supports them.

---

## 26. Acceptance Criteria

The implementation is complete only when:

1. the copied folder is read directly from the repository;
2. manifest hashes and JSON Schemas are validated;
3. exactly 500 stocks are imported;
4. exactly 97 strategies are imported into the research catalog;
5. the full 11/25/74/163 GICS hierarchy is queryable;
6. the current stock snapshot is not presented as historical membership;
7. existing provider mappings are reused;
8. research readiness and broker readiness are separate;
9. no unimplemented strategy becomes executable;
10. no approximate plugin mapping is labelled exact;
11. point-in-time daily backtests work for the first approved strategy wave;
12. costs, walk-forward validation, robustness, and multiple-testing controls work;
13. candidate scoring follows the supplied protocol;
14. recommendations use cached approved candidates;
15. recommendation optimization is GICS-aware;
16. sleeve weights map exactly to stock weights and strategy shares;
17. accepting a recommendation populates existing goal stock and assignment models;
18. accepted weights survive construction preview unchanged;
19. manual builder mode is unchanged;
20. recommendation acceptance creates no orders, rebalance, or strategy instances;
21. current preview remains mandatory;
22. apply still creates one combined rebalance;
23. created or reused strategy instances remain disabled SHADOW;
24. safe strategy deletion leaves construction and recommendation history intact;
25. APIs are paginated and research tasks do not block web workers;
26. recommendation latency is within 3-15 seconds when cached data is current;
27. all backend, gateway, frontend, and streaming tests pass;
28. documentation describes data limitations and unsupported strategies.

---

## 27. Non-Goals

Do not add:

- LIVE trading;
- automatic strategy enablement;
- automatic order submission;
- AI-generated runtime strategy code;
- runtime evaluation of formula strings;
- fake broker contracts;
- automatic historical membership reconstruction from the current snapshot;
- short selling before borrow and risk support exists;
- pair/basket execution through a single-instrument plugin;
- intraday research before the daily framework passes;
- public administrative mutation endpoints without authentication;
- a second provider-mapping source of truth;
- silent changes to existing goal rules;
- silent re-optimization of accepted recommendation weights;
- deletion of existing working Portfolio Builder behavior.

---

## 28. Implementation Discipline

- Work phase by phase.
- Read the existing implementation before changing a file.
- Reuse existing idempotency, audit, task, provider, and safety patterns.
- Remove replaced experimental code completely.
- Do not keep compatibility aliases for code that has been fully migrated.
- Keep migrations deterministic and reversible where practical.
- Keep completed records immutable.
- Add tests with every phase.
- Run the full verification suite before completion.
- Document any unavoidable assumption in `docs/open-questions.md`, then proceed with the safest implementation.
