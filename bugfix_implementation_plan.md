# Trading Engine Bug-Fix Implementation Plan

Repository: `rachitm0897/Trading-Engine`

## 1. Goals

Fix the six identified defects and simplify Finnhub configuration so the System page shows one dialog with:

- Finnhub API key input
- **Test key**
- **Save key**

Remove the administrator sign-in form from the Market Data Providers section.

Keep these rules:

- The API key is stored only in the backend.
- The complete key is never returned to the frontend.
- No `VITE_FINNHUB_*` variable is added.
- Environment configuration remains supported.
- SHADOW remains the default execution mode.
- Existing sizing, risk, OMS, IBKR, ledger, audit, and reconciliation paths remain unchanged.

---

## 2. Fix Optimized Flow Allocation

### Current problem

`PORTFOLIO_OPTIMIZATION` and eligible `AUTO` flows first execute strategy-capital allocation, modify strategy capital, and calculate `unallocated_amount`. They then run portfolio optimization using the full post-flow NAV.

This mixes two allocation systems and can produce inconsistent records.

### Required change

Resolve the final allocation mode before any allocation work.

#### Strategy mode

For `STRATEGY_ALLOCATION`:

- Keep the existing deposit and withdrawal logic.
- Update strategy capital.
- Create strategy allocation decisions.
- Calculate approved and unallocated amounts normally.

#### Optimization mode

For `PORTFOLIO_OPTIMIZATION`:

- Do not run strategy deposit or withdrawal allocation.
- Do not modify `TradingStrategy.allocated_capital`.
- Do not create strategy allocation decisions.
- Calculate post-flow NAV and usable cash.
- Run portfolio optimization.
- Create the SHADOW optimized rebalance.
- Set `approved_amount` based on the valid flow amount.
- Set `unallocated_amount` only from actual cash, lot-size, minimum-notional, or unfunded constraints.
- Store the optimization and rebalance references in the allocation snapshot.

#### AUTO mode

- Resolve to optimization only when an enabled universe and policy exist.
- Otherwise resolve to strategy allocation.
- Save the resolved mode, not `AUTO`, in the final `AllocationRun`.

Add separate service functions so the two paths cannot accidentally execute together.

---

## 3. Prevent Duplicate Application of an Optimization Run

### Current problem

The same completed optimization preview can be applied repeatedly with different idempotency keys, creating multiple rebalances and possible duplicate PAPER orders.

### Required change

- Add an application state or reference on `PortfolioOptimizationRun`, such as:
  - `applied_rebalance`
  - `applied_at`
  - `application_status`
- Enforce that one optimization run can create only one applied rebalance.
- Keep the SHADOW preview rebalance separate from the applied rebalance.
- Use a database transaction and row lock when applying.
- Return the existing applied rebalance for repeated identical requests, or return a clear `OPTIMIZATION_ALREADY_APPLIED` error.
- Disable the Apply button after a run has been applied.
- Show the applied rebalance ID and status in the frontend.

---

## 4. Secure Portfolio Mutation Endpoints

### Current problem

Universe, policy, optimization preview, and optimization apply endpoints are currently unauthenticated and CSRF-exempt.

### Required change

- Remove `csrf_exempt` from portfolio-universe, policy, preview, and apply endpoints.
- Require valid CSRF protection for browser mutations.
- Require POST for mutation operations.
- Preserve idempotency-key requirements for preview, apply, flows, and rebalances.
- Validate that the selected portfolio, universe, policy, and optimization run belong together.
- Add basic request throttling for expensive optimization and Finnhub operations.
- Record audit events for:
  - Universe changes
  - Policy changes
  - Optimization preview
  - Optimization apply
  - Finnhub test
  - Finnhub save

No administrator login UI is required for the Finnhub dialog, but backend access should still be restricted by deployment/network controls because anyone who can call the save endpoint can replace the stored key.

---

## 5. Preserve Failed Finnhub Fetch Records

### Current problem

`fetch_daily_history()` is wrapped in one atomic transaction. When the fetch fails and the exception is re-raised, the failed `MarketDataFetchRun` update is rolled back.

### Required change

- Remove the outer transaction around the full network operation.
- Create the fetch-run record before making the Finnhub request.
- Use a small atomic block only when writing price rows.
- On failure:
  - Save `FAILED`
  - Save the error message
  - Save completion time
  - Preserve any response or rate-limit metadata
  - Re-raise the error after the failure record is committed
- Add a test proving failed fetch runs remain in the database.

---

## 6. Validate Universe Size Instead of Silently Truncating It

### Current problem

The API stores every selected stock, while the optimizer silently uses only the first `maximum_instruments` IDs.

### Required change

Choose explicit validation rather than silent truncation:

- Reject universe saves when enabled selected instruments exceed `maximum_instruments`.
- Return a clear validation error containing both values.
- Also validate again before optimization in case database records were changed externally.
- Remove list slicing from `universe_instruments()`.
- Show the current selected count and maximum count in the frontend.
- Disable Save when the selection exceeds the limit.

---

## 7. Correct Rebalance Turnover Calculation

### Current problem

Turnover is counted using the desired trade quantity before buy quantities are reduced by available cash. This can consume the turnover budget for trades that will not actually occur.

### Required change

For every candidate:

1. Calculate the desired quantity.
2. Apply cash and fee constraints.
3. Determine the final executable quantity.
4. Calculate turnover from the final executable quantity.
5. Apply the turnover limit.
6. Save `planned_turnover` from actual planned trades only.

For sell-before-buy plans:

- Count the actual planned sell quantities.
- Recalculate affordable buys after fills.
- Update planned turnover consistently when buy quantities change.
- Do not count suppressed trades.

Add tests where limited cash reduces the first buy and verify later valid trades are not incorrectly suppressed.

---

## 8. Simplify Finnhub Configuration UI

### Frontend

Remove:

- Administrator username/password form
- Sign-in button
- Sign-out button
- Admin-session status from the Market Data Providers panel

Add one dialog:

#### Fields

- Masked current configuration status
- Password-style Finnhub key input
- Environment source status
- Last successful test
- Last error

#### Buttons

**Test key**

- Tests the key currently entered in the dialog.
- Does not save it.
- Sends it directly to the backend test endpoint.
- Clears the key from component state after the test completes or the dialog closes.

**Save key**

- Encrypts and stores the key through the backend.
- Returns only masked status.
- Clears the input after saving.
- Refreshes provider status.

Do not store the key in:

- Local storage
- Session storage
- Zustand
- TanStack Query cache
- URL parameters
- Logs

### Backend

Update the Finnhub test endpoint so it can accept a transient key:

- If `api_key` is supplied, instantiate `FinnhubClient(api_key=...)`.
- Test it without saving.
- If no key is supplied, test the currently effective stored or environment key.

Update the save endpoint:

- Accept `api_key`.
- Encrypt it.
- Save only encrypted data and the last four characters.
- Never return encrypted or plaintext key material.

Remove the staff-session requirement from Finnhub configure and test endpoints, as requested.

Keep:

- CSRF protection
- POST-only behavior
- Rate limiting
- Audit records using an operator/system actor
- Masked responses
- Environment-key precedence unless database override is explicitly enabled

Remove unused authentication-session frontend code. Remove backend auth-session endpoints only if they are not used elsewhere.

---

## 9. Tests

### Backend tests

Add tests for:

- Optimization flows do not modify strategy capital.
- Strategy flows still preserve the old behavior.
- AUTO resolves correctly.
- Allocation amounts and statuses match the actual optimization result.
- One optimization run cannot be applied twice.
- Failed Finnhub fetch runs remain stored.
- Transient Finnhub key testing does not save the key.
- Saved Finnhub keys are encrypted and masked.
- Universe size validation rejects excess instruments.
- Turnover uses final executable quantities.
- CSRF and idempotency protections remain active.
- Existing SHADOW and PAPER behavior remains intact.

### Frontend tests

Add tests for:

- Finnhub dialog opens without an admin sign-in form.
- Test key does not call Save.
- Save key clears the input.
- The full key never appears after submission.
- Apply is disabled after an optimization run is applied.
- Universe selection count is validated.
- Flow mode displays the resolved allocation mode.

Run:

```bash
cd Backend
pytest
python manage.py check
python manage.py makemigrations --check

cd ../Frontend
npm test
npm run build

cd ..
docker compose config --quiet
```

---

## 10. Delivery Order

1. Separate strategy and optimized flow paths.
2. Add one-time optimization application protection.
3. Fix turnover calculation.
4. Fix Finnhub failed-run persistence.
5. Add universe-size validation.
6. Replace the Finnhub admin sign-in UI with the key dialog.
7. Update Finnhub test/save endpoints.
8. Restore CSRF protection and add throttling/audit events.
9. Add migrations and tests.
10. Run the full existing test suite and Docker configuration checks.

---

## 11. Acceptance Criteria

The fixes are complete when:

- Optimization flows never execute strategy allocation logic.
- Strategy capital is unchanged by optimized flows.
- An optimization preview can be applied only once.
- Failed Finnhub fetch runs remain visible.
- Selected stocks are never silently excluded.
- Planned turnover equals actual planned trades.
- The System page has only a Finnhub key dialog with Test and Save actions.
- Testing a key does not save it.
- Saving a key never exposes it back to the browser.
- Existing execution and reconciliation behavior still passes all tests.
