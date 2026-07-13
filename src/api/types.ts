export type Scalar = string | number | boolean | null
export type JsonRecord = Record<string, unknown>
export type DecimalValue = string | number | null

export interface ApiProblem {
  code: string
  message: string
  details: unknown
}

export interface ApiEnvelope<T> {
  ok: boolean
  data: T | null
  error: ApiProblem | null
  meta: Record<string, unknown>
}

export interface SystemStatus {
  mode: string
  global_kill_switch: boolean
  material_breaks: number
  time: string
}

export interface GatewayStatus {
  connected: boolean
  reconciled: boolean
  mode: string
  last_callback?: string | null
  worker?: string
}

export interface BrokerAccount {
  id: number
  account_id: string
  alias: string
  base_currency: string
  net_liquidation: DecimalValue
  available_cash: DecimalValue
  buying_power: DecimalValue
  daily_pnl: DecimalValue
  is_reconciled: boolean
  kill_switch: boolean
  updated_at: string
}

export interface Portfolio {
  id: number
  name: string
  account_id?: number
  account?: string
  cash_buffer_pct: DecimalValue
  margin_buffer_pct: DecimalValue
  minimum_notional: DecimalValue
  minimum_quantity: DecimalValue
  minimum_drift: DecimalValue
  kill_switch: boolean
}

export interface Instrument {
  id: number
  symbol: string
  asset_class: string
  exchange: string
  primary_exchange: string
  currency: string
  sector: string
  multiplier: DecimalValue
  lot_size: DecimalValue
  min_tick: DecimalValue
  fractional_support: boolean
  trading_calendar: string
  active: boolean
  tradable: boolean
}

export interface Position {
  id: number
  portfolio_id: number
  portfolio: string
  account_id: string
  instrument_id: number
  symbol: string
  asset_class: string
  currency: string
  quantity: DecimalValue
  average_cost: DecimalValue
  market_price: DecimalValue
  market_value: DecimalValue
  updated_at: string
}

export interface Order {
  id: number
  internal_id: string
  account_id: string
  portfolio_id?: number
  symbol: string
  side: string
  order_type: string
  time_in_force: string
  broker_order_id: string
  broker_permanent_id: string
  status: string
  quantity: DecimalValue
  filled_quantity: DecimalValue
  average_fill_price: DecimalValue
  created_at: string
  updated_at: string
}

export interface Execution {
  id: number
  order_id: string
  account_id: string
  symbol: string
  execution_id: string
  quantity: DecimalValue
  price: DecimalValue
  commission: DecimalValue
  currency: string
  executed_at: string
}

export interface AuditEvent {
  id: number
  event_type: string
  actor: string
  aggregate_type: string
  aggregate_id: string
  data: JsonRecord
  created_at: string
}

export interface KillSwitch {
  id: number
  scope: string
  scope_id: string
  enabled: boolean
  reason: string
  updated_at: string
}

export interface RiskDecision {
  id: number
  order_intent_id: number
  check_name: string
  decision: string
  reason: string
  requested_quantity: DecimalValue
  approved_quantity: DecimalValue
  created_at: string
}

export interface RiskSummary {
  kill_switches: KillSwitch[]
  decisions: RiskDecision[]
}

export interface ReconciliationRun {
  id: number
  trigger: string
  status: string
  started_at: string
  completed_at: string | null
}

export interface ReconciliationBreak {
  id: number
  run_id: number
  category: string
  severity: string
  internal_value: unknown
  broker_value: unknown
  material: boolean
  resolved: boolean
  resolution: string
  created_at: string
}

export interface ReconciliationSummary {
  runs: ReconciliationRun[]
  breaks: ReconciliationBreak[]
}

export interface StreamMetric {
  id?: number
  component: string
  metric: string
  status: string
  value: Scalar | JsonRecord
  observed_at: string
}

export interface FlinkJob {
  id?: string
  name?: string
  state?: string
  [key: string]: unknown
}

export interface StreamingHealth {
  kafka_enabled: boolean
  metrics: StreamMetric[]
  flink: {status?: string; jobs?: FlinkJob[]; error?: string}
  outbox_pending: number
  dead_letter_count: number
  stale_instrument_count: number
}

export interface ParameterProperty {
  type?: 'integer' | 'number' | 'string' | 'boolean'
  title?: string
  description?: string
  enum?: Scalar[]
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  default?: Scalar
}

export interface ParameterSchema {
  type?: string
  required?: string[]
  properties?: Record<string, ParameterProperty>
  additionalProperties?: boolean
}

export interface InputRequirement {
  identity_hash?: string
  input_type: string
  name: string
  parameters: JsonRecord
  parameters_hash?: string
  warmup_bars: number
  shared_by?: number
  active?: boolean
}

export interface StrategyDefinition {
  id: number
  key: string
  name: string
  description: string
  plugin_path: string
  input_requirements: InputRequirement[]
  parameter_schema: ParameterSchema
  default_parameters: Record<string, Scalar>
  supported_asset_types: string[]
  supported_directions: string[]
  supported_timeframes: string[]
  version: number
  enabled: boolean
}

export interface StrategyVersion {
  id: number
  version: number
  parameter_hash: string
  configuration_snapshot: JsonRecord
  created_at: string
  activated_at: string | null
  retired_at: string | null
}

export interface StrategyInstance {
  id: number
  name: string
  definition_key: string
  definition_name: string
  portfolio_id: number
  portfolio: string
  instrument_id: number
  symbol: string
  asset_class: string
  exchange: string
  currency: string
  conid: number | null
  primary_exchange: string | null
  timeframe: string
  parameters: JsonRecord
  target_configuration: JsonRecord
  risk_policy_id: number | null
  order_policy_id: number | null
  execution_mode: 'OBSERVE' | 'SHADOW' | 'PAPER'
  state: string
  enabled: boolean
  version: number
  warmup_progress: number
  warmup_required: number
  block_reason: string
  effective_from: string | null
  effective_to: string | null
  last_final_bar: string | null
  latest_indicators: Record<string, DecimalValue>
  latest_signal: string | null
  current_target: DecimalValue
  attributed_quantity: DecimalValue
  active_order: string | null
  last_fill: string | null
  cooldown: string | null
  created_at: string
  updated_at: string
  versions?: StrategyVersion[]
  requirements?: InputRequirement[]
  qualification_command?: JsonRecord | null
}

export interface StrategyTimelineItem {
  time: string
  type: string
  id: number
  status: string
  version: number | null
  detail?: string
}

export interface StrategyChartBar {
  time: string
  open: DecimalValue
  high: DecimalValue
  low: DecimalValue
  close: DecimalValue
  volume: DecimalValue
  version: number
}

export interface StrategyChartIndicator {
  time: string
  name: string
  value: DecimalValue
}

export interface StrategyChartMarker {
  time: string
  type: 'SIGNAL' | 'TARGET' | 'ORDER' | 'FILL'
  label: string
  value?: DecimalValue
}

export interface StrategyChartData {
  bars: StrategyChartBar[]
  indicators: StrategyChartIndicator[]
  markers: StrategyChartMarker[]
  source: string
}

export interface RiskPolicy {
  id: number
  name: string
  maximum_weight: DecimalValue
  maximum_notional: DecimalValue
  maximum_quantity: DecimalValue
  allow_short: boolean
}

export interface OrderPolicy {
  id: number
  name: string
  order_type: string
  time_in_force: string
  limit_offset_bps: DecimalValue
  price_collar_bps: DecimalValue
  allow_market_order: boolean
  replace_after_seconds: number
  maximum_replacements: number
  cancel_at_session_end: boolean
  outside_regular_hours: boolean
}

export interface StrategyPolicies {
  risk_policies: RiskPolicy[]
  order_policies: OrderPolicy[]
}

export interface InstrumentResolution {
  instrument_id: number
  symbol: string
  asset_class: string
  exchange: string
  currency: string
  conid: number | null
  primary_exchange: string | null
  qualification_command: JsonRecord | null
}

export interface InstrumentSearchResult {
  symbol: string
  local_symbol: string
  conid: number
  asset_class: string
  exchange: string
  primary_exchange: string
  currency: string
  description: string
  instrument_id: number | null
}

export interface SeriesPoint {
  time: string
  value: number
}

export interface ExposurePoint {
  time: string
  gross: number
  net: number
}

export interface InstrumentAllocation {
  instrument_id: number
  symbol: string
  value: number
  weight: number
}

export interface PortfolioSeries {
  portfolio_id: number
  source: string
  nav: SeriesPoint[]
  pnl: SeriesPoint[]
  exposure: ExposurePoint[]
  allocation_by_instrument: InstrumentAllocation[]
}

export interface AttentionItem {
  id: string
  severity: 'INFO' | 'WARNING' | 'CRITICAL'
  title: string
  detail: string
}

export interface DashboardSummary {
  mode: string
  account: BrokerAccount | null
  portfolio: Portfolio | null
  gateway: GatewayStatus | null
  gateway_error?: string | null
  reconciliation_status: string
  nav: DecimalValue
  cash: DecimalValue
  buying_power: DecimalValue
  daily_pnl: DecimalValue
  gross_exposure: DecimalValue
  net_exposure: DecimalValue
  active_strategies: number
  open_orders: number
  positions: number
  recent_activity: AuditEvent[]
  attention: AttentionItem[]
  updated_at: string
}

export interface AllocationPolicy {
  id: number
  portfolio_id: number
  portfolio: string
  strategy_id: number
  strategy: string
  target_share: DecimalValue
  minimum_share: DecimalValue
  maximum_share: DecimalValue
  capacity: DecimalValue
  minimum_allocation: DecimalValue
  priority: number
  enabled: boolean
}

export interface AllocationRun {
  id: number
  flow_id: number
  portfolio_id: number
  flow_type: string
  amount: DecimalValue
  approved_amount: DecimalValue
  unallocated_amount: DecimalValue
  liquidation_policy: string
  status: string
  created_at: string
}

export interface RebalancePolicy {
  id: number
  portfolio_id: number
  instrument_drift_threshold: DecimalValue
  portfolio_drift_threshold: DecimalValue
  minimum_trade_notional: DecimalValue
  minimum_trade_quantity: DecimalValue
  cash_buffer_percent: DecimalValue
  fee_buffer: DecimalValue
  maximum_turnover: DecimalValue
  sell_before_buy: boolean
  price_staleness_limit: number
  partial_fill_threshold: DecimalValue
  mode: string
  enabled: boolean
  updated_at: string
}

export interface RebalanceTarget {
  id: number
  instrument_id: number
  target_weight: DecimalValue
  current_weight: DecimalValue
  drift: DecimalValue
  current_quantity: DecimalValue
  target_quantity: DecimalValue
  trade_quantity: DecimalValue
  reference_price: DecimalValue
  estimated_cost: DecimalValue
  suppressed: boolean
  suppression_reason: string
  rank: number
}

export interface RebalanceRun {
  id: number
  portfolio_id: number
  trigger: string
  mode: string
  status: string
  phase: string
  nav: DecimalValue
  total_drift: DecimalValue
  planned_turnover: DecimalValue
  created_at: string
  last_recalculated_at: string | null
  targets?: RebalanceTarget[]
}

export interface PositionSizingDecision {
  id: number
  instrument_id: number
  side: string
  target_quantity: DecimalValue
  risk_quantity: DecimalValue
  weight_quantity: DecimalValue
  liquidity_quantity: DecimalValue
  cash_quantity: DecimalValue
  broker_quantity: DecimalValue
  approved_quantity: DecimalValue
  binding_constraint: string
  rejected_reason: string
}
