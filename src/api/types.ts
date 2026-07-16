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
  execution_mode?: string
  is_admin?: boolean
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

export interface OrderStatusHistory {
  id: number
  from_status: string
  to_status: string
  broker_status: string
  reason_code: string
  reason: string
  source: string
  details: JsonRecord
  occurred_at: string
  operator_requested: boolean
}

export interface OrderDetail {
  order: Order
  status_history: OrderStatusHistory[]
  broker_diagnostics: OrderStatusHistory[]
  risk_decisions: JsonRecord[]
  fills: JsonRecord[]
  strategy_attribution: JsonRecord[]
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
  data_path_status: string
  data_path_reasons: string[]
  gateway: {status: string; value: JsonRecord; observed_at: string | null}
  consumer: {status: string; last_heartbeat: string | null; age_seconds?: number; value: JsonRecord}
  metrics: StreamMetric[]
  flink: {status?: string; jobs?: FlinkJob[]; error?: string}
  strategies: StrategyStreamStatus[]
  outbox_pending: number
  outbox_failed: number
  dead_letter_count: number
  stale_instrument_count: number
}

export interface StrategyStreamStatus {
  strategy_id: number
  strategy: string
  symbol: string
  timeframe: string
  status: string
  subscription_state: string
  conid: number | null
  last_raw_event: string | null
  last_canonical_event: string | null
  last_final_bar: string | null
  warmup_progress: number
  warmup_required: number
  last_indicator: string | null
  last_strategy_run: string | null
  last_error: string
  missing: string[]
  stale_after_seconds: number
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
  warmup_started_at: string | null
  warmup_last_progress_at: string | null
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
  streaming?: StrategyStreamStatus
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
  allocation_mode: string
  optimization_run_id: number | null
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
  target_source: string
  optimization_run_id: number | null
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

export interface FinnhubProviderStatus {
  provider: 'FINNHUB'
  configured: boolean
  enabled: boolean
  effective_source: 'ENVIRONMENT' | 'DATABASE' | 'NONE'
  environment_configured: boolean
  database_configured: boolean
  database_override_requested: boolean
  database_override_allowed: boolean
  database_override_active: boolean
  masked_api_key: string
  last_success_at: string | null
  last_tested_at: string | null
  last_test_success_at: string | null
  last_error: string
  rate_limit_state: Record<string, string>
  updated_at: string | null
  connected?: boolean
  source?: 'TRANSIENT' | 'ENVIRONMENT' | 'DATABASE'
}

export interface PortfolioUniverse {
  id: number
  portfolio_id: number
  name: string
  include_strategy_instruments: boolean
  minimum_history_observations: number
  maximum_instruments: number
  selected_count: number
  enabled: boolean
  instruments: {instrument_id: number; symbol: string; enabled: boolean}[]
  updated_at: string
}

export interface PortfolioOptimizationPolicy {
  id: number
  portfolio_id: number
  name: string
  method: 'MINIMUM_VARIANCE' | 'MAXIMUM_SHARPE'
  lookback_days: number
  return_estimation: string
  covariance_estimation: string
  risk_free_rate: DecimalValue
  target_cash_weight: DecimalValue
  minimum_weight: DecimalValue
  maximum_weight: DecimalValue
  maximum_turnover: DecimalValue
  transaction_cost_penalty: DecimalValue
  long_only: boolean
  enabled: boolean
  execution_mode: 'SHADOW' | 'PAPER'
  version: number
  updated_at: string
}

export interface OptimizedPortfolioTarget {
  id: number
  instrument_id: number
  symbol: string
  current_weight: DecimalValue
  optimized_weight: DecimalValue
  weight_change: DecimalValue
  target_value: DecimalValue
  expected_return_contribution: DecimalValue
  risk_contribution: DecimalValue
  constraint_status: string
  rank: number
}

export interface PlannedOptimizationTrade {
  instrument_id: number
  symbol: string
  side: 'BUY' | 'SELL' | 'NONE'
  quantity: DecimalValue
  reference_price: DecimalValue
  estimated_cost: DecimalValue
  suppressed: boolean
  suppression_reason: string
}

export interface PortfolioOptimizationRun {
  id: number
  portfolio_id: number
  policy_id: number
  universe_id: number
  trigger: string
  status: string
  input_start_date: string | null
  input_end_date: string | null
  nav: DecimalValue
  objective_value: DecimalValue
  expected_return: DecimalValue
  expected_volatility: DecimalValue
  sharpe_ratio: DecimalValue
  turnover: DecimalValue
  cash_weight: DecimalValue
  solver_status: string
  warnings: unknown[]
  error_details: JsonRecord
  flow_reference: string
  application_status: 'NOT_APPLIED' | 'APPLYING' | 'APPLIED'
  applied_at: string | null
  created_at: string
  completed_at: string | null
  targets?: OptimizedPortfolioTarget[]
  planned_trades?: PlannedOptimizationTrade[]
  rebalance?: {id: number; mode: string; status: string; phase: string; planned_turnover: DecimalValue} | null
  applied_rebalance?: {id: number; mode: string; status: string; phase: string; planned_turnover: DecimalValue} | null
}

export type GoalTimeframe = 'NOW' | 'HURRY' | 'FAST' | 'BUILD' | 'GROW' | 'COMPOUND'

export interface GoalResolvedRules {
  timeframe_bucket: GoalTimeframe
  timeframe_label: string
  risk_level: number
  risk_code: string
  risk_label: string
  maximum_allowed_risk: number
  minimum_cash_weight: DecimalValue
  maximum_stock_weight: DecimalValue
  optimizer_method: 'MINIMUM_VARIANCE' | 'MAXIMUM_SHARPE' | null
  lookback_days: number
  minimum_history_observations: number
  long_only: boolean
}

export interface PortfolioGoalAllocation {
  id: number
  plan_id: number
  name: string
  allocation_weight: DecimalValue
  allocation_percentage: DecimalValue
  timeframe_bucket: GoalTimeframe
  risk_level: number
  enabled: boolean
  display_order: number
  construction_source: 'MANUAL_OPTIMIZER' | 'ACCEPTED_RECOMMENDATION'
  accepted_recommendation_run_id: number | null
  resolved_rules: GoalResolvedRules
  instrument_count: number
  created_at: string
  updated_at: string
}

export interface ConstructionValidationError {
  code: string
  message: string
  goal_id?: number
  allocated_weight?: DecimalValue
}

export interface PortfolioConstructionPlan {
  id: number
  portfolio_id: number
  name: string
  status: 'DRAFT' | 'ACTIVE' | 'PAUSED'
  version: number
  allocated_weight: DecimalValue
  allocated_percentage: DecimalValue
  enabled_goal_count: number
  ready_to_preview: boolean
  validation_errors: ConstructionValidationError[]
  timeframe_options: {code: GoalTimeframe; label: string}[]
  risk_options: {level: number; code: string; label: string}[]
  goals: PortfolioGoalAllocation[]
  created_at: string
  updated_at: string
}

export interface ConstructionStrategyOption {
  strategy_definition_id: number
  key: string
  name: string
  summary: string
  limitations: string
  execution_timeframes: string[]
  default_parameters: Record<string, Scalar>
  parameter_schema: ParameterSchema
  eligible: boolean
  reason: string
}

export interface ConstructionEligibility {
  goal_id: number
  eligible: ConstructionStrategyOption[]
  rejected: ConstructionStrategyOption[]
}

export interface GoalInstrumentSelection {
  id: number
  goal_id: number
  instrument_id: number
  symbol: string
  asset_class: string
  exchange: string
  currency: string
  minimum_weight: DecimalValue | null
  maximum_weight: DecimalValue | null
  display_order: number
  enabled: boolean
  assignment_count: number
  created_at: string
  updated_at: string
}

export interface GoalStrategyAssignment {
  id: number
  goal_instrument_id: number
  goal_id: number
  strategy_definition_id: number
  strategy_key: string
  strategy_name: string
  instrument_id: number
  symbol: string
  execution_timeframe: string
  parameter_overrides: JsonRecord
  parameter_hash: string
  strategy_share: DecimalValue
  risk_policy_id: number | null
  order_policy_id: number | null
  create_instance: boolean
  enabled: boolean
  created_strategy_instance_id: number | null
  created_at: string
  updated_at: string
}

export interface GoalConstructionStrategy {
  assignment_id: number
  strategy_definition_id: number
  strategy_name: string
  strategy_share: DecimalValue
  portfolio_weight: DecimalValue
}

export interface GoalConstructionStock {
  instrument_id: number
  symbol: string
  goal_instrument_id: number
  goal_id: number
  goal_name: string
  goal_allocation_weight: DecimalValue
  local_weight: DecimalValue
  portfolio_contribution: DecimalValue
  strategy_share_total: DecimalValue
  strategy_share_valid: boolean
  strategies: GoalConstructionStrategy[]
}

export interface GoalConstructionResult {
  goal_id: number
  name: string
  allocation_weight: DecimalValue
  goal_nav: DecimalValue
  timeframe_bucket: GoalTimeframe
  risk_level: number
  optimizer_method: string | null
  construction_source: 'MANUAL_OPTIMIZER' | 'ACCEPTED_RECOMMENDATION'
  accepted_recommendation_run_id: number | null
  cash_weight: DecimalValue
  maximum_stock_weight: DecimalValue
  stocks: GoalConstructionStock[]
  metrics: {expected_return: DecimalValue; expected_volatility: DecimalValue; sharpe_ratio: DecimalValue}
  warnings: {code: string; message?: string}[]
  intentionally_cash_only: boolean
  apply_blocked: boolean
}

export interface ResearchDatasetVersion {
  id: number
  bundle_name: string
  version: string
  snapshot_date: string
  status: string
  manifest_hash: string
  validation_report: {counts?: Record<string, number>; current_snapshot_only?: boolean; warnings?: string[]}
  imported_at: string | null
  activated_at: string | null
}

export interface ResearchUniverse {
  id: number
  key: string
  name: string
  description: string
  dataset_version_id: number
  dataset_version: string
  membership_type: 'CURRENT_SNAPSHOT' | 'POINT_IN_TIME'
  active: boolean
  member_count: number
}

export interface ResearchStrategy {
  id: number
  research_id: string
  name: string
  family: string
  scope: string
  role: string
  production_status: string
  supported_directions: string[]
  supported_frequencies: string[]
  active: boolean
  dataset_version_id: number
  implementation_statuses: string[]
}

export interface ResearchReadiness {
  id: number
  research_id: string
  as_of_date: string
  data_ready: boolean
  features_ready: boolean
  implementation_ready: boolean
  backtest_ready: boolean
  approved: boolean
  builder_ready: boolean
  blocking_reasons: string[]
}

export interface ResearchCandidateScore {
  id: number
  research_id: string
  instrument_id: number | null
  symbol: string | null
  goal_timeframe: GoalTimeframe
  risk_level: number
  as_of_date: string
  score: DecimalValue
  eligible: boolean
  hard_rejection_reasons: string[]
  expires_at: string
}

export interface GoalRecommendationSleeve {
  id: number
  instrument_id: number
  symbol: string
  gics: {
    sector?: {code: string; name: string}
    industry_group?: {code: string; name: string}
    industry?: {code: string; name: string}
    sub_industry?: {code: string; name: string}
  }
  research_id: string
  strategy_name: string
  strategy_family: string
  execution_strategy_definition_id: number
  execution_timeframe: string
  parameters: JsonRecord
  sleeve_weight: DecimalValue
  stock_weight: DecimalValue
  strategy_share: DecimalValue
  candidate_score: DecimalValue
  expected_return: DecimalValue
  expected_volatility: DecimalValue
  expected_drawdown: DecimalValue
  cost_metrics: JsonRecord
  rationale: string
  rank: number
}

export interface GoalRecommendationRun {
  id: number
  goal_id: number
  requested_plan_version: number
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  as_of_date: string
  metrics: {cash_weight?: DecimalValue; expected_return?: DecimalValue; expected_volatility?: DecimalValue; sleeve_count?: number}
  warnings: {code: string; message?: string}[]
  error: string
  expires_at: string
  accepted_at: string | null
  dataset_version_id: number
  protocol_version_id: number
  created_at: string
  sleeves?: GoalRecommendationSleeve[]
}

export interface PortfolioConstructionTarget {
  id: number
  instrument_id: number
  symbol: string
  current_weight: DecimalValue
  target_weight: DecimalValue
  weight_change: DecimalValue
  target_value: DecimalValue
  expected_return_contribution: DecimalValue
  risk_contribution: DecimalValue
  goal_contributions: {goal_id: number; goal_name: string; local_weight: DecimalValue; portfolio_contribution: DecimalValue}[]
  shared_across_goals: boolean
  rank: number
}

export interface PlannedConstructionTrade extends PlannedOptimizationTrade {
  current_weight: DecimalValue
  target_weight: DecimalValue
}

export interface PortfolioConstructionRun {
  id: number
  plan_id: number
  portfolio_id: number
  status: string
  application_status: 'NOT_APPLIED' | 'QUEUED' | 'APPLYING' | 'APPLIED' | 'FAILED'
  retryable: boolean
  last_error: string
  attempt_count: number
  nav: DecimalValue
  final_target_weights: {cash?: DecimalValue; stocks?: Record<string, DecimalValue>}
  metrics: {
    expected_return?: DecimalValue
    expected_volatility?: DecimalValue
    sharpe_ratio?: DecimalValue
    strategy_targets?: {
      identity: string
      strategy_definition_id: number
      strategy_name: string
      instrument_id: number
      symbol: string
      execution_timeframe: string
      target_weight: DecimalValue
      assignment_ids: number[]
    }[]
    strategy_instances?: {assignment_id: number; strategy_instance_id: number; target_weight: DecimalValue}[]
  }
  warnings: unknown[]
  goals?: GoalConstructionResult[]
  targets?: PortfolioConstructionTarget[]
  planned_trades?: PlannedConstructionTrade[]
  rebalance?: {id: number; mode: string; status: string; phase: string; planned_turnover: DecimalValue} | null
  applied_rebalance?: {id: number; mode: string; status: string; phase: string; planned_turnover: DecimalValue} | null
  applied_at: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}
