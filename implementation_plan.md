# Trading Engine Portfolio Construction and Markowitz Flow Allocation
## Implementation Plan

Repository: `rachitm0897/Trading-Engine`

## 1. Objective

Extend the existing trading engine so that:

1. A portfolio can be constructed across multiple stocks using Markowitz optimization.
2. Deposits, withdrawals, and rebalancing use optimized portfolio weights.
3. Finnhub supplies historical and reference market data.
4. The frontend allows an administrator to configure and test the Finnhub API key safely.
5. The existing strategy, risk, OMS, IBKR Gateway, ledger, reconciliation, and SHADOW/PAPER execution flow remains intact.

The optimizer should produce target portfolio weights. The existing rebalancing system should continue converting those targets into auditable order intents.

---

## 2. Target Architecture

```text
Portfolio Universe / Strategy Signals
                |
                v
        Finnhub Market Data
                |
                v
 Expected Returns + Covariance
                |
                v
      Portfolio Optimizer
                |
                v
 Optimized Portfolio Target Set
                |
                v
 Existing Rebalancing Service
                |
                v
 Position Sizing -> Risk -> OMS -> IBKR
                |
                v
 Ledgers -> Reconciliation -> Audit
```

Portfolio flows should use the same pipeline:

```text
Deposit / Withdrawal
        |
        v
Calculate Post-Flow NAV
        |
        v
Run Portfolio Optimizer
        |
        v
Generate New Target Weights
        |
        v
Create Rebalance Preview or Run
```

---

## 3. Backend Implementation

### Phase 1: Finnhub configuration and data provider

Add a dedicated market-data provider module.

Required responsibilities:

- Read `FINNHUB_API_KEY` and `FINNHUB_BASE_URL` from environment variables.
- Support an encrypted database-stored API key configured from the frontend.
- Prefer the environment key unless database override is explicitly enabled.
- Provide a connection-test endpoint.
- Never return the full API key to the frontend.
- Record provider status, last successful request, last error, and rate-limit information.
- Add retries, timeout handling, rate-limit handling, and structured error messages.

Recommended environment variables:

```env
FINNHUB_API_KEY=
FINNHUB_BASE_URL=https://finnhub.io/api/v1
FINNHUB_API_KEY_OVERRIDE_ENABLED=false
FINNHUB_REQUEST_TIMEOUT_SECONDS=15
```

Do not allow arbitrary `.env` upload or editing through the frontend.

### Phase 2: Historical market-data storage

Add durable storage for adjusted daily price history.

Suggested entities:

- `MarketDataProviderConfiguration`
- `InstrumentPriceHistory`
- `MarketDataFetchRun`

Store:

- Instrument
- Trading date
- Open, high, low, close
- Adjusted close when available
- Volume
- Provider
- Fetch timestamp
- Data version
- Quality or completeness status

Add Celery tasks for:

- Initial history download
- Incremental daily updates
- Missing-data repair
- Stale-data checks

Use PostgreSQL initially. TimescaleDB can be introduced later if the data volume requires it.

### Phase 3: Portfolio optimization models

Add models such as:

#### `PortfolioOptimizationPolicy`

Fields should include:

- Portfolio
- Method
- Lookback period
- Return estimation method
- Covariance estimation method
- Risk-aversion value
- Risk-free rate
- Minimum stock weight
- Maximum stock weight
- Maximum sector weight
- Target cash weight
- Allow shorting
- Maximum gross exposure
- Maximum turnover
- Transaction-cost penalty
- Minimum observations
- Enabled flag
- Default SHADOW/PAPER mode

Supported methods:

- Minimum variance
- Maximum Sharpe ratio
- Risk-aversion utility
- Target return
- Target volatility

#### `PortfolioOptimizationRun`

Store an immutable optimization record:

- Portfolio
- Policy version
- Trigger
- Status
- Input start and end dates
- NAV
- Current weights
- Expected returns
- Covariance matrix or a reproducible covariance snapshot
- Constraints
- Solver status
- Objective value
- Expected return
- Expected volatility
- Sharpe ratio
- Turnover
- Warnings
- Error details
- Created and completed timestamps

#### `OptimizedPortfolioTarget`

Store:

- Optimization run
- Instrument
- Current weight
- Optimized weight
- Weight change
- Target value
- Expected contribution to return
- Contribution to risk
- Constraint status
- Rank

Every rebalance produced from optimization should reference its `PortfolioOptimizationRun`.

### Phase 4: Optimization service

Create a standalone optimizer service with no broker or HTTP responsibilities.

Inputs:

- Stock universe
- Price history
- Current portfolio weights
- Available cash
- Portfolio NAV
- Policy constraints
- Optional strategy signals or confidence scores

Outputs:

- Optimized stock weights
- Cash weight
- Expected portfolio return
- Expected volatility
- Sharpe ratio
- Estimated turnover
- Warnings and binding constraints

Recommended calculation flow:

1. Align price histories by date.
2. Reject instruments with insufficient observations.
3. Calculate periodic returns.
4. Estimate expected returns.
5. Estimate covariance.
6. Regularize the covariance matrix.
7. Solve the constrained optimization.
8. Validate that weights and constraints are satisfied.
9. Save an immutable optimization run.
10. Pass the optimized target weights to rebalancing.

Use transaction-cost-aware optimization:

\[
\max_w \left(\mu^T w - \lambda w^T\Sigma w - \kappa\lVert w-w_{current}\rVert_1\right)
\]

The first implementation should be long-only by default.

### Phase 5: Portfolio universe management

Add portfolio-level universe configuration.

The universe should support:

- Manual stock selection
- Inclusion from active strategy instruments
- Excluded instruments
- Minimum history requirement
- Maximum number of stocks
- Sector metadata where available

Do not treat each stock as a separate portfolio. One portfolio should own a set of instruments and one optimization policy.

### Phase 6: Rebalancing integration

Modify target generation, not the execution pipeline.

Current flow:

```text
Strategy targets -> aggregate target weights -> rebalance
```

New flow:

```text
Strategy targets or portfolio universe
        -> optimizer
        -> optimized target weights
        -> existing rebalance planner
```

The rebalancing service should accept a target source:

- `STRATEGY_AGGREGATION`
- `PORTFOLIO_OPTIMIZATION`

For optimized runs:

- Load target weights from the selected optimization run.
- Preserve current drift checks.
- Preserve minimum trade notional and quantity.
- Preserve cash buffer.
- Preserve turnover limits.
- Preserve sell-before-buy behavior.
- Preserve position sizing, risk, OMS, order attribution, ledgers, and reconciliation.
- Keep SHADOW preview as the default.
- Do not enable LIVE execution.

Add the optimization run ID and target-source information to the rebalance snapshot and audit events.

### Phase 7: Markowitz-based flow allocation

Replace stock-level flow handling with post-flow optimization.

#### Deposit

1. Create the flow record.
2. Calculate post-deposit NAV.
3. Reserve the configured cash buffer.
4. Run optimization using the new NAV.
5. Compare current values with optimized target values.
6. Create buy and sell quantities through the rebalance planner.
7. Keep residual cash when lot sizes or minimum-notional constraints prevent full allocation.

#### Withdrawal

1. Use available cash first.
2. Calculate post-withdrawal NAV.
3. Run optimization using the reduced NAV.
4. Generate sales from positions above their optimized target values.
5. Respect liquidity, turnover, minimum trade size, and risk constraints.
6. Report any unfunded withdrawal amount.

The existing strategy-level capital accounting may remain, but it should not independently dictate stock trades when the portfolio optimization mode is enabled.

### Phase 8: APIs

Add endpoints similar to:

- `GET /api/v1/data-providers/finnhub/`
- `POST /api/v1/data-providers/finnhub/configure/`
- `POST /api/v1/data-providers/finnhub/test/`
- `GET /api/v1/portfolio-optimization/policies/`
- `POST /api/v1/portfolio-optimization/policies/`
- `GET /api/v1/portfolio-optimization/runs/`
- `POST /api/v1/portfolio-optimization/preview/`
- `POST /api/v1/portfolio-optimization/run/`
- `GET /api/v1/portfolio-optimization/runs/:id/`
- `GET /api/v1/portfolio-universe/`
- `POST /api/v1/portfolio-universe/`

All modifying endpoints should require idempotency keys where appropriate.

---

## 4. Frontend Implementation

### Portfolio page

Add a `Portfolio Construction` section containing:

- Portfolio universe selector
- Instrument search and multi-select
- Optimization method
- Lookback period
- Risk-aversion control
- Minimum and maximum weight
- Target cash percentage
- Maximum turnover
- Optional sector limits
- Preview optimization button
- Apply through rebalance button

Display:

- Current versus optimized allocation
- Expected return
- Expected volatility
- Sharpe ratio
- Estimated turnover
- Cash weight
- Required trades
- Binding constraints
- Data freshness
- Excluded instruments and reasons
- Solver warnings

The user should preview before creating a PAPER rebalance.

### Flow allocation section

Extend the existing flow form with:

- Allocation mode: existing strategy allocation or portfolio optimization
- Optimization policy
- Preview result
- Post-flow NAV
- Optimized weights
- Planned buys and sells
- Unallocated or unfunded amount

### System page

Add a `Market Data Providers` section.

Finnhub controls:

- Masked API key input
- Save or replace key
- Environment-key status
- Database-override status
- Test connection
- Last successful request
- Last error
- Rate-limit state

The frontend must never receive or display the complete stored key.

---

## 5. Security Requirements

Before frontend credential management is exposed:

- Add authentication to backend APIs.
- Restrict provider configuration to administrators.
- Encrypt database-stored API keys.
- Mask secrets in responses and logs.
- Do not store secrets in Redux, Zustand, local storage, query cache, or browser build variables.
- Do not expose the Finnhub key as a `VITE_*` environment variable.
- Add audit events for creating, replacing, testing, and disabling provider credentials.
- Never provide arbitrary `.env` file editing from the browser.

---

## 6. Testing Plan

### Unit tests

Test:

- Return calculations
- Covariance calculations
- Covariance regularization
- Constraint validation
- Minimum-variance optimization
- Maximum-Sharpe optimization
- Turnover penalty
- Cash-weight handling
- Missing and stale data
- Deposit optimization
- Withdrawal optimization
- Lot rounding
- Minimum-notional suppression
- Idempotent optimization and flow requests
- Finnhub retries and rate-limit errors
- API key masking and precedence

### Integration tests

Verify:

- Finnhub data is fetched and stored.
- Optimization produces valid weights.
- Optimization targets create a SHADOW rebalance.
- Rebalancing still passes through sizing, risk, OMS, and audit.
- Deposit and withdrawal flows trigger correct post-flow targets.
- Existing strategy aggregation still works when optimization is disabled.
- Existing IBKR Gateway behavior remains unchanged.

### Frontend tests

Verify:

- Universe and policy forms validate correctly.
- Optimization preview renders.
- Flow preview renders.
- API keys remain masked.
- No secret is written to browser storage.
- Existing Portfolio and System pages continue working.

---

## 7. Delivery Order

1. Add Finnhub backend configuration and connection testing.
2. Add historical price storage and Celery synchronization.
3. Add optimization policies, runs, targets, and services.
4. Add portfolio-universe management.
5. Integrate optimized targets into SHADOW rebalancing.
6. Integrate deposit and withdrawal flows.
7. Add frontend portfolio construction.
8. Add frontend Finnhub configuration.
9. Add tests, migrations, documentation, and Docker environment variables.
10. Run the full existing test suite and confirm no regression in IBKR, OMS, reconciliation, or streaming.

---

## 8. Acceptance Criteria

The implementation is complete when:

- An operator can select several stocks for one portfolio.
- Finnhub historical data can be fetched and refreshed.
- A Markowitz optimization preview produces valid multi-stock target weights.
- The preview displays expected return, volatility, Sharpe ratio, cash, turnover, and warnings.
- A deposit or withdrawal generates post-flow optimized targets.
- Optimized targets pass through the existing rebalance, risk, OMS, IBKR, ledger, and reconciliation pipeline.
- SHADOW remains the default execution mode.
- The Finnhub key can be configured and tested securely from the frontend.
- Environment-based Finnhub configuration continues to work.
- The API key is never exposed in browser responses, logs, or frontend build variables.
- Existing tests pass and new backend and frontend tests cover the added behavior.
