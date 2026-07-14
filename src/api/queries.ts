import {queryOptions} from '@tanstack/react-query'
import {request, withQuery} from './client'
import type {
  AllocationPolicy,
  AllocationRun,
  AdminSession,
  AuditEvent,
  BrokerAccount,
  DashboardSummary,
  Execution,
  GatewayStatus,
  Instrument,
  Order,
  OrderDetail,
  Portfolio,
  PortfolioSeries,
  Position,
  RebalancePolicy,
  RebalanceRun,
  ReconciliationSummary,
  RiskSummary,
  StrategyChartData,
  StrategyDefinition,
  StrategyInstance,
  StrategyPolicies,
  StrategyTimelineItem,
  StreamingHealth,
  SystemStatus,
  FinnhubProviderStatus,
  PortfolioUniverse,
  PortfolioOptimizationPolicy,
  PortfolioOptimizationRun,
} from './types'

const POLL_INTERVAL = 15_000

export const queries = {
  authSession: () => queryOptions({
    queryKey: ['auth-session'],
    queryFn: () => request<AdminSession>('auth/session/'),
    staleTime: 30_000,
  }),
  system: () => queryOptions({
    queryKey: ['system'],
    queryFn: () => request<SystemStatus>('system/'),
    refetchInterval: POLL_INTERVAL,
  }),
  gateway: () => queryOptions({
    queryKey: ['gateway'],
    queryFn: () => request<GatewayStatus>('gateway/'),
    refetchInterval: POLL_INTERVAL,
  }),
  accounts: () => queryOptions({
    queryKey: ['accounts'],
    queryFn: () => request<BrokerAccount[]>('accounts/'),
    refetchInterval: POLL_INTERVAL,
  }),
  portfolios: () => queryOptions({
    queryKey: ['portfolios'],
    queryFn: () => request<Portfolio[]>('portfolios/'),
    refetchInterval: POLL_INTERVAL,
  }),
  instruments: () => queryOptions({
    queryKey: ['instruments'],
    queryFn: () => request<Instrument[]>('instruments/'),
    staleTime: 60_000,
  }),
  positions: (portfolioId?: number | null) => queryOptions({
    queryKey: ['positions', portfolioId ?? 'all'],
    queryFn: () => request<Position[]>(withQuery('positions/', {portfolio: portfolioId})),
    refetchInterval: POLL_INTERVAL,
  }),
  dashboard: (portfolioId?: number | null) => queryOptions({
    queryKey: ['dashboard', portfolioId ?? 'default'],
    queryFn: () => request<DashboardSummary>(withQuery('dashboard/summary/', {portfolio: portfolioId})),
    refetchInterval: POLL_INTERVAL,
  }),
  portfolioSeries: (portfolioId?: number | null) => queryOptions({
    queryKey: ['portfolio-series', portfolioId ?? 'default'],
    queryFn: () => request<PortfolioSeries>(withQuery('portfolios/series/', {portfolio: portfolioId})),
    refetchInterval: 30_000,
  }),
  orders: (filters: {portfolioId?: number | null; status?: string; symbol?: string} = {}) => queryOptions({
    queryKey: ['orders', filters],
    queryFn: () => request<Order[]>(withQuery('orders/', {
      portfolio: filters.portfolioId,
      status: filters.status,
      symbol: filters.symbol,
      limit: 250,
    })),
    refetchInterval: POLL_INTERVAL,
  }),
  orderDetail: (internalId: string) => queryOptions({
    queryKey: ['order-detail', internalId],
    queryFn: () => request<OrderDetail>(`orders/${internalId}/detail/`),
    enabled: Boolean(internalId),
    refetchInterval: POLL_INTERVAL,
  }),
  executions: (filters: {portfolioId?: number | null; symbol?: string} = {}) => queryOptions({
    queryKey: ['executions', filters],
    queryFn: () => request<Execution[]>(withQuery('executions/', {
      portfolio: filters.portfolioId,
      symbol: filters.symbol,
      limit: 250,
    })),
    refetchInterval: POLL_INTERVAL,
  }),
  audit: (filters: {eventType?: string; limit?: number} = {}) => queryOptions({
    queryKey: ['audit', filters],
    queryFn: () => request<AuditEvent[]>(withQuery('audit/', {
      event_type: filters.eventType,
      limit: filters.limit ?? 100,
    })),
    refetchInterval: POLL_INTERVAL,
  }),
  risk: () => queryOptions({
    queryKey: ['risk'],
    queryFn: () => request<RiskSummary>('risk/'),
    refetchInterval: POLL_INTERVAL,
  }),
  reconciliation: () => queryOptions({
    queryKey: ['reconciliation'],
    queryFn: () => request<ReconciliationSummary>('reconciliation/'),
    refetchInterval: POLL_INTERVAL,
  }),
  streaming: () => queryOptions({
    queryKey: ['streaming'],
    queryFn: () => request<StreamingHealth>('streaming/health/'),
    refetchInterval: POLL_INTERVAL,
  }),
  strategyDefinitions: () => queryOptions({
    queryKey: ['strategy-definitions'],
    queryFn: () => request<StrategyDefinition[]>('strategy-definitions/'),
    staleTime: 5 * 60_000,
  }),
  strategyPolicies: () => queryOptions({
    queryKey: ['strategy-policies'],
    queryFn: () => request<StrategyPolicies>('strategy-policies/'),
    staleTime: 60_000,
  }),
  strategies: (filters: {portfolioId?: number | null; state?: string; executionMode?: string} = {}) => queryOptions({
    queryKey: ['strategy-instances', filters],
    queryFn: () => request<StrategyInstance[]>(withQuery('strategy-instances/', {
      portfolio: filters.portfolioId,
      state: filters.state,
      execution_mode: filters.executionMode,
    })),
    refetchInterval: POLL_INTERVAL,
  }),
  strategy: (strategyId: number) => queryOptions({
    queryKey: ['strategy-instance', strategyId],
    queryFn: () => request<StrategyInstance>(`strategy-instances/${strategyId}/`),
    enabled: strategyId > 0,
    refetchInterval: POLL_INTERVAL,
  }),
  strategyTimeline: (strategyId: number) => queryOptions({
    queryKey: ['strategy-timeline', strategyId],
    queryFn: () => request<StrategyTimelineItem[]>(`strategy-instances/${strategyId}/execution-timeline/`),
    enabled: strategyId > 0,
    refetchInterval: POLL_INTERVAL,
  }),
  strategyChart: (strategyId: number) => queryOptions({
    queryKey: ['strategy-chart', strategyId],
    queryFn: () => request<StrategyChartData>(`strategy-instances/${strategyId}/chart/`),
    enabled: strategyId > 0,
    refetchInterval: POLL_INTERVAL,
  }),
  allocationPolicies: () => queryOptions({
    queryKey: ['allocation-policies'],
    queryFn: () => request<AllocationPolicy[]>('allocations/policies/'),
    staleTime: 30_000,
  }),
  allocationRuns: () => queryOptions({
    queryKey: ['allocation-runs'],
    queryFn: () => request<AllocationRun[]>('allocations/runs/'),
    refetchInterval: POLL_INTERVAL,
  }),
  rebalancePolicies: () => queryOptions({
    queryKey: ['rebalance-policies'],
    queryFn: () => request<RebalancePolicy[]>('rebalancing/policies/'),
    staleTime: 30_000,
  }),
  rebalanceRuns: () => queryOptions({
    queryKey: ['rebalance-runs'],
    queryFn: () => request<RebalanceRun[]>('rebalancing/runs/'),
    refetchInterval: POLL_INTERVAL,
  }),
  finnhub: () => queryOptions({
    queryKey: ['finnhub'],
    queryFn: () => request<FinnhubProviderStatus>('data-providers/finnhub/'),
    staleTime: 30_000,
  }),
  portfolioUniverse: (portfolioId?: number | null) => queryOptions({
    queryKey: ['portfolio-universe', portfolioId ?? 'none'],
    queryFn: () => request<PortfolioUniverse[]>(withQuery('portfolio-universe/', {portfolio: portfolioId})),
    enabled: Boolean(portfolioId),
    staleTime: 30_000,
  }),
  optimizationPolicies: (portfolioId?: number | null) => queryOptions({
    queryKey: ['optimization-policies', portfolioId ?? 'none'],
    queryFn: () => request<PortfolioOptimizationPolicy[]>(withQuery('portfolio-optimization/policies/', {portfolio: portfolioId})),
    enabled: Boolean(portfolioId),
    staleTime: 30_000,
  }),
  optimizationRuns: (portfolioId?: number | null) => queryOptions({
    queryKey: ['optimization-runs', portfolioId ?? 'none'],
    queryFn: () => request<PortfolioOptimizationRun[]>(withQuery('portfolio-optimization/runs/', {portfolio: portfolioId})),
    enabled: Boolean(portfolioId),
    refetchInterval: POLL_INTERVAL,
  }),
}
