import {render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App, {appBasename, normalizeBasename} from '../src/App'
import {queryClient} from '../src/app/queryClient'
import {usePreferencesStore} from '../src/stores/preferences'

const definition = {
  id: 44, key: 'CUSTOM_BREAKOUT', name: 'Backend Breakout', description: 'A backend-provided portable definition.', plugin_path: 'plugins.Custom',
  supported_timeframes: ['15m', '1h'], supported_asset_types: ['STK'], supported_directions: ['LONG'], version: 3, enabled: true,
  default_parameters: {lookback: 21, confirmation: 'CLOSE'}, input_requirements: [{input_type: 'INDICATOR', name: 'channel', parameters: {window: 21}, warmup_bars: 22}],
  parameter_schema: {type: 'object', required: ['lookback', 'confirmation'], properties: {lookback: {type: 'integer', minimum: 2}, confirmation: {enum: ['CLOSE', 'INTRABAR']}}},
}

const strategy = {
  id: 7, name: 'Portable breakout', definition_key: definition.key, definition_name: definition.name,
  portfolio_id: 10, portfolio: 'Primary paper', instrument_id: 5, symbol: 'NVDA', asset_class: 'STK', exchange: 'SMART', currency: 'USD',
  conid: 4815747, primary_exchange: 'NASDAQ', timeframe: '15m', parameters: definition.default_parameters,
  target_configuration: {target_weight: 0.1, capital_share: 1, priority: 100}, risk_policy_id: null, order_policy_id: null,
  execution_mode: 'SHADOW', state: 'LONG', enabled: true, version: 2, warmup_progress: 22, warmup_required: 22,
  block_reason: '', effective_from: '2026-07-13T00:00:00Z', effective_to: null, last_final_bar: '2026-07-13T01:00:00Z',
  latest_indicators: {channel: 123}, latest_signal: 'ENTER_LONG', current_target: 0.1, attributed_quantity: 4,
  active_order: 'order-active', last_fill: 'fill-1', cooldown: null, created_at: '2026-07-12T00:00:00Z', updated_at: '2026-07-13T01:00:00Z',
  streaming: {strategy_id: 7, strategy: 'Portable breakout', symbol: 'NVDA', timeframe: '15m', status: 'HEALTHY',
    subscription_state: 'ACTIVE', conid: 4815747, last_raw_event: '2026-07-13T01:00:01Z',
    last_canonical_event: '2026-07-13T01:00:02Z', last_final_bar: '2026-07-13T01:00:00Z', warmup_progress: 22,
    warmup_required: 22, last_indicator: '2026-07-13T01:00:03Z', last_strategy_run: '2026-07-13T01:00:04Z', last_error: '', missing: [], stale_after_seconds: 1800},
  versions: [{id: 2, version: 2, parameter_hash: 'abcdef1234567890', configuration_snapshot: {}, created_at: '2026-07-13T00:00:00Z', activated_at: '2026-07-13T00:05:00Z', retired_at: null}],
  requirements: [{identity_hash: 'input-1', input_type: 'INDICATOR', name: 'channel', parameters: {window: 21}, parameters_hash: 'hash', warmup_bars: 22, shared_by: 1, active: true}],
}

const data: Record<string, unknown> = {
  system: {mode: 'PAPER', execution_mode: 'SHADOW', is_admin: true, global_kill_switch: false, material_breaks: 0, time: '2026-07-13T01:00:00Z'},
  'auth/session': {is_authenticated: true, is_admin: true, username: 'admin'},
  gateway: {connected: true, reconciled: true, mode: 'paper', last_callback: '2026-07-13T01:00:00Z', worker: 'paper-worker'},
  accounts: [
    {id: 1, account_id: 'DU-PRIMARY', alias: 'Primary', base_currency: 'USD', net_liquidation: 100000, available_cash: 40000, buying_power: 200000, daily_pnl: 250, is_reconciled: true, kill_switch: false, updated_at: '2026-07-13T01:00:00Z'},
    {id: 2, account_id: 'DU-SECONDARY', alias: 'Secondary', base_currency: 'USD', net_liquidation: 50000, available_cash: 20000, buying_power: 100000, daily_pnl: -25, is_reconciled: true, kill_switch: false, updated_at: '2026-07-13T01:00:00Z'},
  ],
  portfolios: [
    {id: 10, name: 'Primary paper', account_id: 1, account: 'DU-PRIMARY', cash_buffer_pct: .02, margin_buffer_pct: .1, minimum_notional: 10, minimum_quantity: 1, minimum_drift: .001, kill_switch: false},
    {id: 20, name: 'Secondary paper', account_id: 2, account: 'DU-SECONDARY', cash_buffer_pct: .02, margin_buffer_pct: .1, minimum_notional: 10, minimum_quantity: 1, minimum_drift: .001, kill_switch: false},
  ],
  instruments: [{id: 5, symbol: 'NVDA', asset_class: 'STK', exchange: 'SMART', currency: 'USD', sector: 'Technology', multiplier: 1, lot_size: 1, min_tick: .01, fractional_support: false, trading_calendar: 'XNYS', active: true, tradable: true}, {id: 6, symbol: 'MSFT', asset_class: 'STK', exchange: 'SMART', currency: 'USD', sector: 'Technology', multiplier: 1, lot_size: 1, min_tick: .01, fractional_support: false, trading_calendar: 'XNYS', active: true, tradable: true}],
  positions: [{id: 1, portfolio_id: 10, portfolio: 'Primary paper', account_id: 'DU-PRIMARY', instrument_id: 5, symbol: 'NVDA', asset_class: 'STK', currency: 'USD', quantity: 4, average_cost: 100, market_price: 125, market_value: 500, updated_at: '2026-07-13T01:00:00Z'}],
  'dashboard/summary': {mode: 'PAPER', account: null, portfolio: null, gateway: {connected: true, reconciled: true, mode: 'paper'}, reconciliation_status: 'RECONCILED', nav: 100000, cash: 40000, buying_power: 200000, daily_pnl: 250, gross_exposure: 500, net_exposure: 500, active_strategies: 1, open_orders: 1, positions: 1, recent_activity: [], attention: [], updated_at: '2026-07-13T01:00:00Z'},
  'portfolios/series': {portfolio_id: 10, source: 'POSTGRES_MARKET_BARS_WITH_CURRENT_HOLDINGS', nav: [{time: '2026-07-12T00:00:00Z', value: 99000}, {time: '2026-07-13T00:00:00Z', value: 100000}], pnl: [{time: '2026-07-12T00:00:00Z', value: 0}, {time: '2026-07-13T00:00:00Z', value: 1000}], exposure: [{time: '2026-07-12T00:00:00Z', gross: 480, net: 480}, {time: '2026-07-13T00:00:00Z', gross: 500, net: 500}], allocation_by_instrument: [{instrument_id: 5, symbol: 'NVDA', value: 500, weight: 1}]},
  'strategy-definitions': [definition],
  'strategy-policies': {risk_policies: [{id: 1, name: 'Long only'}], order_policies: [{id: 1, name: 'Patient limit'}]},
  'strategy-instances': [strategy],
  'strategy-instances/7': strategy,
  'strategy-instances/7/execution-timeline': [{id: 1, time: '2026-07-13T01:00:00Z', type: 'SIGNAL', status: 'ENTER_LONG', version: 2}],
  'strategy-instances/7/chart': {source: 'POSTGRES_MARKET_AND_EXECUTION_FACTS', bars: [{time: '2026-07-13T01:00:00Z', open: 121, high: 126, low: 120, close: 125, volume: 1000, version: 1}], indicators: [{time: '2026-07-13T01:00:00Z', name: 'channel', value: 123}], markers: [{time: '2026-07-13T01:00:00Z', type: 'SIGNAL', label: 'Signal ENTER_LONG'}]},
  'instruments/search': [{symbol: 'NVDA', local_symbol: 'NVDA', conid: 4815747, asset_class: 'STK', exchange: 'SMART', primary_exchange: 'NASDAQ', currency: 'USD', description: 'NVIDIA Corporation', instrument_id: null}],
  orders: [
    {id: 1, internal_id: 'active-order-123', account_id: 'DU-PRIMARY', portfolio_id: 10, symbol: 'NVDA', side: 'BUY', order_type: 'LMT', time_in_force: 'DAY', broker_order_id: '991', broker_permanent_id: '', status: 'ACKNOWLEDGED', quantity: 10, filled_quantity: 4, average_fill_price: 123, created_at: '2026-07-13T00:00:00Z', updated_at: '2026-07-13T01:00:00Z'},
    {id: 2, internal_id: 'filled-order-456', account_id: 'DU-PRIMARY', portfolio_id: 10, symbol: 'NVDA', side: 'BUY', order_type: 'MKT', time_in_force: 'DAY', broker_order_id: '992', broker_permanent_id: '', status: 'FILLED', quantity: 2, filled_quantity: 2, average_fill_price: 124, created_at: '2026-07-12T00:00:00Z', updated_at: '2026-07-12T01:00:00Z'},
  ],
  'orders/active-order-123/detail': {
    order: {},
    status_history: [
      {id: 101, from_status: 'SUBMITTED', to_status: 'REJECTED', broker_status: 'Inactive', reason_code: '201',
        reason: 'Order rejected - insufficient available equity', source: 'ibkr', details: {why_held: ''},
        occurred_at: '2026-07-13T01:00:00Z', operator_requested: false},
      {id: 102, from_status: 'REJECTED', to_status: 'REJECTED', broker_status: 'Inactive', reason_code: '',
        reason: '', source: 'ibkr', details: {}, occurred_at: '2026-07-13T01:00:01Z', operator_requested: false},
    ],
    broker_diagnostics: [], risk_decisions: [], fills: [], strategy_attribution: [],
  },
  executions: [{id: 1, order_id: 'active-order-123', account_id: 'DU-PRIMARY', symbol: 'NVDA', execution_id: 'fill-1', quantity: 4, price: 123, commission: 1, currency: 'USD', executed_at: '2026-07-13T00:30:00Z'}],
  audit: [],
  risk: {kill_switches: [], decisions: []},
  reconciliation: {runs: [], breaks: []},
  'streaming/health': {kafka_enabled: true, data_path_status: 'HEALTHY', data_path_reasons: [],
    gateway: {status: 'HEALTHY', value: {connected: true, reconciled: true}, observed_at: '2026-07-13T01:00:00Z'},
    consumer: {status: 'HEALTHY', last_heartbeat: '2026-07-13T01:00:00Z', value: {}}, metrics: [],
    flink: {status: 'HEALTHY', jobs: []}, strategies: [strategy.streaming], outbox_pending: 0, outbox_failed: 0,
    dead_letter_count: 0, stale_instrument_count: 0},
  'allocations/policies': [{id: 1, portfolio_id: 10, portfolio: 'Primary paper', strategy_id: 1, strategy: 'Portable breakout', target_share: 1, minimum_share: 0, maximum_share: 1, capacity: null, minimum_allocation: 0, priority: 100, enabled: true}],
  'allocations/runs': [], 'rebalancing/policies': [], 'rebalancing/runs': [],
  'data-providers/finnhub': {provider: 'FINNHUB', configured: true, enabled: true, effective_source: 'ENVIRONMENT', environment_configured: true, database_configured: false, database_override_requested: false, database_override_allowed: false, database_override_active: false, masked_api_key: '••••CRET', last_success_at: '2026-07-13T01:00:00Z', last_tested_at: null, last_error: '', rate_limit_state: {remaining: '59', limit: '60'}, updated_at: null, can_manage: true},
  'portfolio-universe': [{id: 1, portfolio_id: 10, name: 'Default universe', include_strategy_instruments: false, minimum_history_observations: 60, maximum_instruments: 50, enabled: true, instruments: [{instrument_id: 5, symbol: 'NVDA', enabled: true}, {instrument_id: 6, symbol: 'MSFT', enabled: true}], updated_at: '2026-07-13T01:00:00Z'}],
  'portfolio-optimization/policies': [{id: 1, portfolio_id: 10, name: 'Default Markowitz policy', method: 'MINIMUM_VARIANCE', lookback_days: 252, return_estimation: 'HISTORICAL_MEAN', covariance_estimation: 'SAMPLE', risk_free_rate: 0, target_cash_weight: .05, minimum_weight: 0, maximum_weight: .8, maximum_turnover: .5, transaction_cost_penalty: .01, long_only: true, enabled: true, execution_mode: 'SHADOW', version: 1, updated_at: '2026-07-13T01:00:00Z'}],
  'portfolio-optimization/runs': [],
}

const optimizationPreview = {
  id: 91, portfolio_id: 10, policy_id: 1, universe_id: 1, trigger: 'PREVIEW', status: 'COMPLETED', input_start_date: '2025-07-01', input_end_date: '2026-07-01', nav: 100000,
  objective_value: .02, expected_return: .12, expected_volatility: .18, sharpe_ratio: .66, turnover: .24, cash_weight: .05, solver_status: 'Optimization terminated successfully', warnings: [], error_details: {}, flow_reference: '', created_at: '2026-07-13T01:00:00Z', completed_at: '2026-07-13T01:00:01Z',
  targets: [{id: 1, instrument_id: 5, symbol: 'NVDA', current_weight: .1, optimized_weight: .45, weight_change: .35, target_value: 45000, expected_return_contribution: .05, risk_contribution: .08, constraint_status: '', rank: 0}, {id: 2, instrument_id: 6, symbol: 'MSFT', current_weight: 0, optimized_weight: .5, weight_change: .5, target_value: 50000, expected_return_contribution: .07, risk_contribution: .1, constraint_status: '', rank: 1}],
  planned_trades: [{instrument_id: 5, symbol: 'NVDA', side: 'BUY', quantity: 10, reference_price: 125, estimated_cost: 1, suppressed: false, suppression_reason: ''}, {instrument_id: 6, symbol: 'MSFT', side: 'BUY', quantity: 15, reference_price: 400, estimated_cost: 2, suppressed: false, suppression_reason: ''}],
  rebalance: {id: 81, mode: 'SHADOW', status: 'PLANNED', phase: 'SHADOW_COMPLETE', planned_turnover: .24},
}

let failDashboard = false
let adminAuthenticated = true

function apiPath(input: string) {
  const url = new URL(input, 'http://localhost')
  return (url.pathname.split('/api/v1/')[1] || '').replace(/\/$/, '')
}

beforeEach(() => {
  window.history.replaceState({}, '', '/')
  queryClient.clear()
  usePreferencesStore.setState({selectedAccountId: null, selectedPortfolioId: null, navigationOpen: false})
  failDashboard = false
  adminAuthenticated = true
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const path = apiPath(input)
    const method = init?.method || 'GET'
    if (failDashboard && path === 'dashboard/summary') return {ok: false, status: 400, json: async () => ({ok: false, data: null, error: {code: 'DEGRADED', message: 'Summary unavailable', details: {}}, meta: {}})} as Response
    if (method !== 'GET') {
      if (path === 'auth/session') {adminAuthenticated = true; return {ok: true, status: 200, json: async () => ({ok: true, data: {is_authenticated: true, is_admin: true, username: 'admin'}, error: null, meta: {}})} as Response}
      if (path === 'strategy-instances') return {ok: true, status: 201, json: async () => ({ok: true, data: strategy, error: null, meta: {}})} as Response
      if (path === 'instruments/resolve') return {ok: true, status: 200, json: async () => ({ok: true, data: {instrument_id: 5, symbol: 'NVDA', asset_class: 'STK', exchange: 'SMART', currency: 'USD', conid: 4815747, primary_exchange: 'NASDAQ', qualification_command: null}, error: null, meta: {}})} as Response
      if (path === 'orders') return {ok: true, status: 201, json: async () => ({ok: true, data: {internal_id: 'created-order', status: 'QUEUED', decision: 'APPROVED'}, error: null, meta: {}})} as Response
      if (path === 'portfolio-optimization/preview' || path === 'portfolio-optimization/run') return {ok: true, status: 201, json: async () => ({ok: true, data: optimizationPreview, error: null, meta: {}})} as Response
      if (path === 'data-providers/finnhub/configure' || path === 'data-providers/finnhub/test') return {ok: true, status: 200, json: async () => ({ok: true, data: {...data['data-providers/finnhub'] as object, connected: path.endsWith('/test')}, error: null, meta: {}})} as Response
      return {ok: true, status: 200, json: async () => ({ok: true, data: {}, error: null, meta: {}})} as Response
    }
    if (path === 'auth/session') return {ok: true, status: 200, json: async () => ({ok: true, data: adminAuthenticated ? data['auth/session'] : {is_authenticated: false, is_admin: false, username: ''}, error: null, meta: {}})} as Response
    if (path === 'data-providers/finnhub') return {ok: true, status: 200, json: async () => ({ok: true, data: {...data['data-providers/finnhub'] as object, can_manage: adminAuthenticated}, error: null, meta: {}})} as Response
    const result = data[path]
    return {ok: true, status: 200, json: async () => ({ok: true, data: result ?? [], error: null, meta: {}})} as Response
  }))
})

afterEach(() => vi.unstubAllGlobals())

test('renders five bookmarkable primary routes and paper status', async () => {
  render(<App />)
  expect(await screen.findByRole('heading', {name: 'Good overview, Primary paper'})).toBeInTheDocument()
  const nav = screen.getByRole('navigation', {name: 'Primary navigation'})
  const links = within(nav).getAllByRole('link')
  expect(links.map((link) => link.textContent)).toEqual(['Dashboard', 'Strategies', 'Portfolio', 'Orders & Activity', 'System'])
  expect(within(nav).getByRole('link', {name: 'Strategies'})).toHaveAttribute('href', '/strategies')
  expect(screen.getAllByText('PAPER').length).toBeGreaterThan(0)
})

test('supports deep links, arbitrary tickers, dynamic schema fields, and shadow-only creation', async () => {
  const user = userEvent.setup()
  window.history.replaceState({}, '', '/strategies/new')
  render(<App />)
  expect(await screen.findByRole('heading', {name: 'Create a strategy'})).toBeInTheDocument()
  await user.type(screen.getByLabelText('Ticker'), 'nvda')
  await user.click(await screen.findByRole('button', {name: 'Select NVDA NASDAQ USD'}))
  await user.click(screen.getByRole('button', {name: 'Qualify selected contract'}))
  await screen.findByText('QUALIFIED')
  await user.click(screen.getByRole('button', {name: 'Continue'}))
  await user.type(screen.getByLabelText('Instance name'), 'NVDA portable')
  await user.selectOptions(screen.getByLabelText('Strategy definition'), 'CUSTOM_BREAKOUT')
  expect(screen.getByLabelText('Timeframe')).toHaveValue('15m')
  await user.click(screen.getByRole('button', {name: 'Continue'}))
  expect(screen.getByLabelText('lookback')).toHaveValue(21)
  expect(screen.getByLabelText('confirmation')).toHaveValue('CLOSE')
  await user.click(screen.getByRole('button', {name: 'Continue'}))
  const mode = screen.getByLabelText('Execution mode')
  expect(mode).toHaveValue('SHADOW')
  expect(screen.queryByRole('option', {name: 'LIVE'})).not.toBeInTheDocument()
  expect(screen.getByText('Advanced policy settings').closest('details')).not.toHaveAttribute('open')
})

test('selected account updates the available portfolio context', async () => {
  const user = userEvent.setup()
  render(<App />)
  const account = await screen.findByLabelText('Selected account')
  await waitFor(() => expect(screen.getByLabelText('Selected portfolio')).toHaveValue('10'))
  await user.selectOptions(account, '2')
  await waitFor(() => expect(screen.getByLabelText('Selected portfolio')).toHaveValue('20'))
  expect(screen.getByRole('option', {name: 'Secondary paper'})).toBeInTheDocument()
})

test('strategy controls expose eligible enable pause and confirmed flatten actions', async () => {
  const user = userEvent.setup()
  window.history.replaceState({}, '', '/strategies')
  render(<App />)
  expect(await screen.findByRole('heading', {name: 'Strategies'})).toBeInTheDocument()
  expect(await screen.findByRole('button', {name: 'Enable Portable breakout'})).toBeDisabled()
  expect(screen.getByRole('button', {name: 'Pause Portable breakout'})).toBeEnabled()
  await user.click(screen.getByRole('button', {name: 'Flatten Portable breakout'}))
  expect(screen.getByRole('dialog', {name: 'Flatten Portable breakout target?'})).toBeInTheDocument()
  expect(screen.getByRole('button', {name: 'Create flat target'})).toBeDisabled()
})

test('kill switch requires confirmation and an audit reason', async () => {
  const user = userEvent.setup()
  window.history.replaceState({}, '', '/system')
  render(<App />)
  await user.click(await screen.findByRole('button', {name: 'Engage global'}))
  const dialog = screen.getByRole('dialog', {name: 'Confirm global trading halt'})
  const confirm = within(dialog).getByRole('button', {name: 'Engage kill switch'})
  expect(confirm).toBeDisabled()
  await user.type(within(dialog).getByLabelText('Reason'), 'Broker state is inconsistent')
  expect(confirm).toBeEnabled()
  await user.click(confirm)
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining('/risk/'), expect.objectContaining({method: 'POST'})))
  const call = vi.mocked(fetch).mock.calls.find(([input, init]) => String(input).includes('/risk/') && init?.method === 'POST')
  expect(String(call?.[1]?.body)).toContain('Broker state is inconsistent')
  expect(screen.getByText('Active strategy data paths')).toBeInTheDocument()
  expect(screen.getByText('22 / 22')).toBeInTheDocument()
})

test('portfolio construction previews optimized metrics and planned SHADOW trades', async () => {
  const user = userEvent.setup()
  window.history.replaceState({}, '', '/portfolio')
  render(<App />)
  expect(await screen.findByRole('heading', {name: 'Portfolio construction'})).toBeInTheDocument()
  await waitFor(() => {
    expect(queryClient.getQueryData(['portfolio-universe', 10])).toEqual(data['portfolio-universe'])
    expect(queryClient.getQueryData(['optimization-policies', 10])).toEqual(data['portfolio-optimization/policies'])
  })
  const previewButton = await screen.findByRole('button', {name: 'Preview optimization'})
  await waitFor(() => expect(previewButton).toBeEnabled())
  await user.click(previewButton)
  expect(await screen.findByText('Current versus optimized allocation')).toBeInTheDocument()
  expect(screen.getByText('Planned trades')).toBeInTheDocument()
  expect(screen.getAllByText('SHADOW').length).toBeGreaterThan(0)
  expect(screen.getByRole('button', {name: 'Apply through SHADOW rebalance'})).toBeInTheDocument()
})

test('admin can replace a masked Finnhub key without exposing it in browser storage', async () => {
  const user = userEvent.setup()
  window.history.replaceState({}, '', '/system')
  render(<App />)
  const input = await screen.findByLabelText('Finnhub API key')
  expect(input).toHaveAttribute('placeholder', '••••CRET')
  expect(input).toHaveValue('')
  await user.type(input, 'replacement-secret')
  await user.click(screen.getByRole('button', {name: 'Save provider'}))
  await waitFor(() => expect(input).toHaveValue(''))
  const call = vi.mocked(fetch).mock.calls.find(([requestInput, init]) => String(requestInput).includes('/data-providers/finnhub/configure/') && init?.method === 'POST')
  expect(String(call?.[1]?.body)).toContain('replacement-secret')
  expect(localStorage.getItem('replacement-secret')).toBeNull()
  expect(JSON.stringify(queryClient.getQueryData(['finnhub']))).not.toContain('replacement-secret')
})

test('Finnhub credential controls require an administrator session', async () => {
  adminAuthenticated = false
  const user = userEvent.setup()
  window.history.replaceState({}, '', '/system')
  render(<App />)
  expect(await screen.findByLabelText('Administrator username')).toBeInTheDocument()
  expect(screen.queryByLabelText('Finnhub API key')).not.toBeInTheDocument()
  await user.type(screen.getByLabelText('Administrator username'), 'admin')
  await user.type(screen.getByLabelText('Administrator password'), 'password')
  await user.click(screen.getByRole('button', {name: 'Sign in to manage providers'}))
  expect(await screen.findByLabelText('Finnhub API key')).toBeInTheDocument()
})

test('strategy detail maps backend chart data with no placeholder series', async () => {
  const user = userEvent.setup()
  window.history.replaceState({}, '', '/strategies/7')
  render(<App />)
  expect(await screen.findByRole('heading', {name: 'Portable breakout'})).toBeInTheDocument()
  await user.click(screen.getByRole('tab', {name: 'Chart'}))
  expect(await screen.findByText(/POSTGRES_MARKET_AND_EXECUTION_FACTS/)).toBeInTheDocument()
  expect(screen.getByRole('img', {name: /Strategy price, indicator, signal, target, order, and fill chart/})).toBeInTheDocument()
})

test('order drawer displays the exact broker rejection reason and explicit empty fallback', async () => {
  const user = userEvent.setup()
  window.history.replaceState({}, '', '/activity')
  render(<App />)
  await user.click(await screen.findByRole('button', {name: 'active-order'}))
  expect(await screen.findByText(/Code 201 · Order rejected - insufficient available equity · ibkr · IBKR Inactive/)).toBeInTheDocument()
  expect(screen.getByText(/No broker reason received · ibkr · IBKR Inactive/)).toBeInTheDocument()
})

test('keeps the shell usable during a route-level partial failure', async () => {
  failDashboard = true
  render(<App />)
  expect(await screen.findByText('Dashboard summary is unavailable')).toBeInTheDocument()
  expect(screen.getByRole('link', {name: 'System'})).toBeInTheDocument()
  expect(screen.getByRole('button', {name: 'Retry'})).toBeInTheDocument()
})

test('uses the API and application base path contracts', async () => {
  render(<App />)
  await waitFor(() => expect(fetch).toHaveBeenCalled())
  expect(String(vi.mocked(fetch).mock.calls[0][0])).toContain('/api/v1/')
  expect(appBasename()).toBe('/')
  expect(normalizeBasename('/trading_eng_frontend/')).toBe('/trading_eng_frontend')
})

test('responsive navigation has an accessible mobile toggle', async () => {
  render(<App />)
  expect(await screen.findByRole('button', {name: 'Open navigation'})).toBeInTheDocument()
})
