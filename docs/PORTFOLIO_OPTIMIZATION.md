# Multi-stock portfolio construction

The portfolio-construction feature produces immutable target weights and passes them to the existing rebalance planner. It does not submit broker orders directly.

```text
Portfolio universe -> Finnhub daily history -> Markowitz optimizer
  -> immutable optimized targets -> rebalance planner
  -> position sizing -> risk -> OMS -> IBKR Gateway
  -> ledgers -> audit -> reconciliation
```

`NEW_EXECUTION_MODE=SHADOW` remains the default. Optimization previews and optimized deposit/withdrawal plans are always SHADOW. Applying a preview can only use `SHADOW` or `PAPER`; LIVE is neither accepted by the optimization policy nor supported by the rebalance service.

## Configuration

Add these server-side settings to the deployment environment:

```env
FINNHUB_API_KEY=
FINNHUB_BASE_URL=https://finnhub.io/api/v1
FINNHUB_API_KEY_OVERRIDE_ENABLED=false
FINNHUB_REQUEST_TIMEOUT_SECONDS=15
FINNHUB_MAX_RETRIES=2
FINNHUB_ENCRYPTION_KEY=
```

`FINNHUB_API_KEY` is preferred. A Django staff user may save an encrypted database credential on the System page, but it overrides an environment credential only when the saved override flag and `FINNHUB_API_KEY_OVERRIDE_ENABLED=true` are both set. Use a stable, independently managed `FINNHUB_ENCRYPTION_KEY` in production. If it is omitted, the backend derives an encryption key from `DJANGO_SECRET_KEY`.

Create the initial administrator with `python manage.py createsuperuser` (or the deployment's normal Django user-provisioning process), then use the staff sign-in shown in the System page.

Credentials are sent to Finnhub in `X-Finnhub-Token`. API responses only include a masked suffix. The frontend has no `VITE_FINNHUB_*` setting, never receives encrypted material, and provides no arbitrary `.env` editor. Save and test operations require an authenticated active Django staff session, a valid CSRF token, and create audit records. Staff users can establish or end that session in the System page without persisting their password in browser storage.

Finnhub `/stock/candle` supplies split-adjusted daily OHLCV history. Finnhub currently documents stock candles as a premium endpoint, so the account must have access. The connection test uses an `AAPL` quote.

## Portfolio controls

On the Portfolio page:

1. Select at least two active stocks in one portfolio universe.
2. Configure minimum variance or maximum Sharpe, lookback, minimum observations, min/max stock weights, target cash, maximum turnover, risk-free rate, and transaction-cost penalty.
3. Save the universe and policy.
4. Preview optimization. Metrics include expected return, volatility, Sharpe ratio, cash, turnover, allocation changes, exclusions, warnings, and planned SHADOW trades.
5. Apply the immutable preview through rebalancing. Under the default configuration it stays SHADOW. If an operator has deliberately enabled existing PAPER mode, the planner creates normal sizing records and order intents for subsequent risk and OMS processing.

The first release is long-only. Weight feasibility is checked before solving. Covariance is regularized when needed. Completed runs store input dates, current weights, expected returns, covariance, constraints, policy version, solver status, metrics, and target-level return/risk contributions.

## Deposit and withdrawal behavior

Flow allocation accepts `AUTO`, `PORTFOLIO_OPTIMIZATION`, or `STRATEGY_ALLOCATION`:

- `AUTO` uses optimization when an enabled universe and policy exist; otherwise it preserves strategy-capital allocation behavior.
- `PORTFOLIO_OPTIMIZATION` requires the universe and policy and fails atomically if post-flow targets cannot be calculated.
- `STRATEGY_ALLOCATION` preserves the previous behavior.

Deposits use post-deposit NAV and cash. Withdrawals use reduced NAV and cash after consuming available cash. Both create an immutable optimization run and SHADOW rebalance plan, preserving lot sizes, minimum notional, drift, cash buffers, turnover, and sell-before-buy sequencing.

## Operations

```powershell
cd Backend
..\.venv\Scripts\python.exe manage.py migrate
..\.venv\Scripts\python.exe -m pytest

cd ..\Frontend
npm test
npm run build
```

Celery Beat queues universe history synchronization and staleness checks every six hours. Initial previews repair insufficient or stale history on demand. Fetch runs retain record counts, completion status, errors, and rate-limit headers.

## API endpoints

- `GET /api/v1/data-providers/finnhub/`
- `GET|POST|DELETE /api/v1/auth/session/`
- `POST /api/v1/data-providers/finnhub/configure/` (staff only)
- `POST /api/v1/data-providers/finnhub/test/` (staff only)
- `GET|POST /api/v1/portfolio-universe/`
- `GET|POST /api/v1/portfolio-optimization/policies/`
- `POST /api/v1/portfolio-optimization/preview/`
- `POST /api/v1/portfolio-optimization/run/`
- `GET /api/v1/portfolio-optimization/runs/`
- `GET /api/v1/portfolio-optimization/runs/<id>/`

Preview and run endpoints require `Idempotency-Key`. The run endpoint requires a completed `optimization_run_id`, enforcing preview-before-apply and preserving the exact target set.
