import {QueryClient, QueryClientProvider} from '@tanstack/react-query'
import {render, screen, waitFor, within} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import {MemoryRouter} from 'react-router-dom'
import {afterEach, beforeEach, describe, expect, test, vi} from 'vitest'
import {ApiError} from '../src/api/client'
import type {
  BrokerGatewaySession,
  BrokerSessionAccount,
  Instrument,
  ManualOrderIntentStatus,
  Order,
  Portfolio,
  Position,
} from '../src/api/types'
import {ManualOrderTicket} from '../src/features/orders/ManualOrderTicket'
import {OrdersActivityPage} from '../src/features/orders/OrdersActivityPage'
import {
  buildManualOrderPayload,
  initialManualOrderDraft,
  type ManualOrderDraft,
  type ManualOrderPayload,
  type ManualOrderType,
} from '../src/features/orders/manualOrder'
import {usePreferencesStore} from '../src/stores/preferences'
import {useWorkspacePreferences} from '../src/stores/workspacePreferences'

const now = '2026-07-24T00:00:00Z'
const session: BrokerGatewaySession = {
  id: '11111111-1111-4111-8111-111111111111',
  display_name: 'Paper Gateway',
  username_hint: 'p***r',
  mode: 'paper',
  status: 'CONNECTED',
  connected: true,
  commands_enabled: true,
  container_status: 'running',
  account_count: 1,
  last_error: '',
  last_gateway_state: {reconciled: true},
  created_at: now,
  updated_at: now,
  provisioned_at: now,
  connected_at: now,
  last_checked_at: now,
  deleted_at: null,
  needs_novnc: false,
  novnc_url: null,
}
const account: BrokerSessionAccount = {
  id: 1,
  account_id: 'DU-PAPER',
  alias: 'Paper account',
  base_currency: 'USD',
  net_liquidation: '100000.00',
  available_cash: '50000.00',
  buying_power: '100000.00',
  daily_pnl: '0',
  is_reconciled: true,
  kill_switch: false,
  updated_at: now,
  available: true,
  last_seen_at: now,
  default_portfolio_id: 10,
}
const portfolio: Portfolio = {
  id: 10,
  name: 'Primary paper',
  account_id: account.id,
  account: account.account_id,
  gateway_session_id: session.id,
  cash_buffer_pct: '0.02',
  margin_buffer_pct: '0.05',
  minimum_notional: '1',
  minimum_quantity: '0.00000001',
  minimum_drift: '0',
  kill_switch: false,
}
const instrument: Instrument = {
  id: 5,
  symbol: 'NVDA',
  asset_class: 'STK',
  exchange: 'SMART',
  primary_exchange: 'NASDAQ',
  currency: 'USD',
  sector: 'Technology',
  multiplier: '1',
  lot_size: '1',
  min_tick: '0.01',
  fractional_support: true,
  trading_calendar: 'XNYS',
  active: true,
  tradable: true,
}
const position: Position = {
  id: 1,
  portfolio_id: portfolio.id,
  portfolio: portfolio.name,
  account_id: account.account_id,
  instrument_id: instrument.id,
  symbol: instrument.symbol,
  asset_class: instrument.asset_class,
  currency: instrument.currency,
  quantity: '12.50000000',
  average_cost: '100.00',
  market_price: '125.25',
  market_value: '1565.625',
  updated_at: now,
}
const queuedResult: ManualOrderIntentStatus = {
  intent_id: 91,
  origin: 'MANUAL',
  operation_status: 'PENDING',
  retryable: false,
  message: 'Manual order intent accepted for asynchronous execution',
}

function renderTicket(overrides: Partial<React.ComponentProps<typeof ManualOrderTicket>> = {}) {
  const onSubmit = vi.fn()
  render(<ManualOrderTicket
    instruments={[instrument]}
    positions={[position]}
    session={session}
    account={account}
    portfolio={portfolio}
    pending={false}
    polling={false}
    pollTimedOut={false}
    error={null}
    onSubmit={onSubmit}
    {...overrides}
  />)
  return onSubmit
}

async function fillTicket(user: ReturnType<typeof userEvent.setup>, orderType: ManualOrderType) {
  await user.selectOptions(screen.getByLabelText('Instrument'), String(instrument.id))
  await user.selectOptions(screen.getByLabelText('Order type'), orderType)
  await user.type(screen.getByLabelText('Quantity'), '1.23456789')
  if (orderType === 'STP' || orderType === 'STP_LMT') await user.type(screen.getByLabelText('Stop price'), '121.12500001')
  if (orderType === 'LMT' || orderType === 'STP_LMT') await user.type(screen.getByLabelText('Limit price'), '120.87500002')
  await user.click(screen.getByRole('button', {name: 'Review manual order'}))
  const dialog = screen.getByRole('dialog', {name: 'Confirm manual order'})
  await user.click(within(dialog).getByRole('button', {name: 'Confirm and queue'}))
}

describe.each([
  ['MKT', {}],
  ['LMT', {limit_price: '120.87500002'}],
  ['STP', {stop_price: '121.12500001'}],
  ['STP_LMT', {stop_price: '121.12500001', limit_price: '120.87500002'}],
] as const)('%s manual order payload', (orderType, expectedPrices) => {
  test('sends exactly the fields accepted by the backend contract', async () => {
    const user = userEvent.setup()
    const onSubmit = renderTicket()
    await fillTicket(user, orderType)
    expect(onSubmit).toHaveBeenCalledOnce()
    expect(onSubmit).toHaveBeenCalledWith({
      instrument_id: 5,
      side: 'BUY',
      order_type: orderType,
      quantity: '1.23456789',
      time_in_force: 'DAY',
      ...expectedPrices,
    })
    const payload = onSubmit.mock.calls[0][0] as ManualOrderPayload
    expect(payload).not.toHaveProperty('reference_price')
    if (orderType === 'MKT') {
      expect(payload).not.toHaveProperty('limit_price')
      expect(payload).not.toHaveProperty('stop_price')
    }
  })
})

test('omits populated but irrelevant price fields after order type changes', () => {
  const draft: ManualOrderDraft = {
    ...initialManualOrderDraft,
    instrumentId: '5',
    quantity: '1.00000001',
    limitPrice: '100.12',
    stopPrice: '99.25',
  }
  expect(buildManualOrderPayload(draft)).toEqual({
    instrument_id: 5,
    side: 'BUY',
    order_type: 'MKT',
    quantity: '1.00000001',
    time_in_force: 'DAY',
  })
})

test('disables submission without an eligible portfolio and shows the reason', () => {
  renderTicket({portfolio: null})
  expect(screen.getByRole('button', {name: 'Review manual order'})).toBeDisabled()
  expect(screen.getByText('Select an eligible portfolio.')).toBeInTheDocument()
})

test('disables submission for an unavailable Gateway route and shows every blocker', () => {
  renderTicket({
    session: {...session, connected: false, status: 'DISCONNECTED', commands_enabled: false, last_error: 'Socket closed'},
    account: {...account, available: false, is_reconciled: false},
  })
  expect(screen.getByRole('button', {name: 'Review manual order'})).toBeDisabled()
  expect(screen.getByText(/disconnected: Socket closed/)).toBeInTheDocument()
  expect(screen.getByText(/Gateway commands are disabled/)).toBeInTheDocument()
  expect(screen.getByText(/Account DU-PAPER is unavailable/)).toBeInTheDocument()
  expect(screen.getByText(/unresolved reconciliation requirements/)).toBeInTheDocument()
})

test('shows a 202 intent as queued and never claims it entered OMS', () => {
  renderTicket({result: queuedResult, polling: true})
  expect(screen.getByText('Manual order accepted and queued for risk and execution.')).toBeInTheDocument()
  expect(screen.getByText(/Intent/)).toHaveTextContent('91')
  expect(screen.queryByText('Manual order entered OMS.')).not.toBeInTheDocument()
})

test('shows HELD reason and retry state honestly', () => {
  renderTicket({result: {...queuedResult, retryable: true, message: 'Account reconciliation is incomplete'}, polling: true})
  expect(screen.getByText('HELD · PENDING')).toBeInTheDocument()
  expect(screen.getByText('Account reconciliation is incomplete')).toBeInTheDocument()
  expect(screen.getByText(/the system will retry: yes/)).toBeInTheDocument()
})

test('preserves backend rejection status, code, message, and details', () => {
  renderTicket({error: new ApiError('Risk policy maximum notional exceeded', 422, 'RISK_REJECTED', {check_name: 'MAX_NOTIONAL'})})
  expect(screen.getByText('RISK_REJECTED')).toBeInTheDocument()
  expect(screen.getByText(/HTTP 422 · Risk policy maximum notional exceeded/)).toBeInTheDocument()
  expect(screen.getByText('Structured details')).toBeInTheDocument()
})

test('renders the LIVE-disabled backend response clearly', () => {
  renderTicket({
    session: {...session, mode: 'live'},
    error: new ApiError('Live manual order routing is disabled by the current execution policy', 403, 'LIVE_MANUAL_TRADING_DISABLED', {allow_live_trading: false}),
  })
  expect(screen.getAllByText(/LIVE manual order routing is disabled/).length).toBeGreaterThan(0)
  expect(screen.getByText('LIVE_MANUAL_TRADING_DISABLED')).toBeInTheDocument()
  expect(screen.getByText(/HTTP 403/)).toBeInTheDocument()
})

type MockApiOptions = {
  post?: (init?: RequestInit) => Promise<Response>
  intent?: () => ManualOrderIntentStatus
}

let testQueryClient: QueryClient | null = null

function envelope(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ok: status >= 200 && status < 300, data: status >= 200 && status < 300 ? data : null, error: status >= 400 ? data : null, meta: {}}),
  } as Response
}

function orderRow(internalId = 'manual-order-001'): Order {
  return {
    id: 71,
    internal_id: internalId,
    account_id: account.account_id,
    portfolio_id: portfolio.id,
    origin: 'MANUAL',
    symbol: instrument.symbol,
    side: 'BUY',
    order_type: 'MKT',
    time_in_force: 'DAY',
    broker_order_id: '',
    broker_permanent_id: '',
    status: 'QUEUED',
    quantity: '1.23456789',
    filled_quantity: '0',
    average_fill_price: null,
    created_at: now,
    updated_at: now,
  }
}

function installMockApi(options: MockApiOptions = {}) {
  let currentOrders: Order[] = []
  const post = options.post || (async () => envelope(queuedResult, 202))
  vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
    const url = new URL(input, 'http://localhost')
    const path = (url.pathname.split('/api/v1/')[1] || '').replace(/\/$/, '')
    const method = init?.method || 'GET'
    if (path === 'orders' && method === 'POST') return post(init)
    if (path === 'orders/intents/91/status') {
      const value = options.intent?.() || queuedResult
      if (value.internal_id) currentOrders = [orderRow(value.internal_id)]
      return envelope(value)
    }
    if (path === 'broker-sessions') return envelope([session])
    if (path === `broker-sessions/${session.id}/accounts`) return envelope([account])
    if (path === 'accounts') return envelope([account])
    if (path === 'portfolios') return envelope([portfolio])
    if (path === 'instruments') return envelope([instrument])
    if (path === 'positions') return envelope([position])
    if (path === 'orders') return envelope(currentOrders)
    if (path === 'executions') return envelope([])
    if (path === 'audit') return envelope([])
    if (path === 'orders/manual-order-001/detail') return envelope({
      order: orderRow(),
      status_history: [{id: 1, from_status: '', to_status: 'QUEUED', broker_status: '', reason_code: '', reason: 'Created by worker', source: 'oms', details: {}, occurred_at: now, operator_requested: false}],
      broker_diagnostics: [],
      risk_decisions: [{id: 1, check_name: 'CAPITAL', decision: 'APPROVED', reason: 'Within policy', requested_quantity: '1.23456789', approved_quantity: '1.23456789', created_at: now}],
      fills: [],
      strategy_attribution: [],
    })
    return envelope([])
  }))
}

function renderOrdersPage(options: MockApiOptions = {}) {
  installMockApi(options)
  usePreferencesStore.setState({selectedSessionId: session.id, selectedAccountId: account.id, selectedPortfolioId: portfolio.id})
  testQueryClient = new QueryClient({defaultOptions: {queries: {retry: false, staleTime: 0}, mutations: {retry: false}}})
  render(<QueryClientProvider client={testQueryClient}><MemoryRouter><OrdersActivityPage /></MemoryRouter></QueryClientProvider>)
}

async function openAndConfirmPageTicket(user: ReturnType<typeof userEvent.setup>, doubleClick = false) {
  const toggle = await screen.findByRole('button', {name: /Manual order ticket/})
  if (toggle.getAttribute('aria-expanded') !== 'true') await user.click(toggle)
  await user.selectOptions(screen.getByLabelText('Instrument'), String(instrument.id))
  await user.type(screen.getByLabelText('Quantity'), '1.23456789')
  await user.click(screen.getByRole('button', {name: 'Review manual order'}))
  const button = within(screen.getByRole('dialog', {name: 'Confirm manual order'})).getByRole('button', {name: 'Confirm and queue'})
  if (doubleClick) await user.dblClick(button)
  else await user.click(button)
}

beforeEach(() => {
  usePreferencesStore.setState({selectedSessionId: null, selectedAccountId: null, selectedPortfolioId: null})
  useWorkspacePreferences.getState().resetWorkspace()
})

afterEach(() => {
  testQueryClient?.clear()
  testQueryClient = null
  vi.unstubAllGlobals()
})

test('one logical submission keeps one idempotency key across transport retry attempts', async () => {
  const keys: string[] = []
  let attempt = 0
  renderOrdersPage({
    post: async (init) => {
      keys.push(new Headers(init?.headers).get('Idempotency-Key') || '')
      attempt += 1
      if (attempt === 1) throw new TypeError('temporary transport failure')
      return envelope({...queuedResult, internal_id: 'manual-order-001', status: 'QUEUED', approved_quantity: '1.23456789', broker_command: null}, 200)
    },
  })
  await openAndConfirmPageTicket(userEvent.setup())
  await waitFor(() => expect(keys).toHaveLength(2), {timeout: 2_000})
  expect(new Set(keys).size).toBe(1)
  expect(keys[0]).not.toBe('')
})

test('double-click confirmation creates only one POST request', async () => {
  let posts = 0
  renderOrdersPage({
    post: async () => {
      posts += 1
      await new Promise((resolve) => setTimeout(resolve, 20))
      return envelope({...queuedResult, internal_id: 'manual-order-001', status: 'QUEUED', approved_quantity: '1.23456789', broker_command: null}, 200)
    },
  })
  await openAndConfirmPageTicket(userEvent.setup(), true)
  await waitFor(() => expect(posts).toBe(1))
})

test('a later OMS result refreshes the blotter and opens the existing order detail view', async () => {
  renderOrdersPage({
    intent: () => ({
      ...queuedResult,
      operation_status: 'QUEUED',
      internal_id: 'manual-order-001',
      status: 'QUEUED',
      approved_quantity: '1.23456789',
      broker_command: {id: 8, command_type: 'PLACE', status: 'PENDING', attempt_count: 0, gateway_command_id: null},
    }),
  })
  await openAndConfirmPageTicket(userEvent.setup())
  expect(await screen.findByText('Manual order entered OMS.')).toBeInTheDocument()
  expect(await screen.findByRole('button', {name: 'manual-order'})).toBeInTheDocument()
  const drawer = await screen.findByRole('dialog', {name: 'NVDA BUY'})
  expect(within(drawer).getByText('MANUAL')).toBeInTheDocument()
  expect(within(drawer).getByText('CAPITAL')).toBeInTheDocument()
  expect(within(drawer).getByRole('button', {name: 'Cancel order'})).toBeEnabled()
})
