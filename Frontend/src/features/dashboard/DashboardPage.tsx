import {useQuery} from '@tanstack/react-query'
import {Activity, AlertTriangle, Banknote, Bot, CircleDollarSign, Landmark, Scale, ShoppingCart} from 'lucide-react'
import {queries} from '../../api/queries'
import {ActivityTimeline} from '../../components/ActivityTimeline'
import {TimeSeriesChart} from '../../components/charts/TimeSeriesChart'
import {ErrorState, Freshness, MetricCard, PageHeader, Panel, Skeleton, StatusBadge, formatMoney, formatNumber} from '../../components/ui'
import {useSelection} from '../../stores/useSelection'

export function DashboardPage() {
  const {portfolio, selectedPortfolioId} = useSelection()
  const summary = useQuery(queries.dashboard(selectedPortfolioId))
  const series = useQuery(queries.portfolioSeries(selectedPortfolioId))

  if (summary.isLoading) return <><PageHeader title="Dashboard" description="A live operating view of the selected portfolio." /><Skeleton lines={6} height={420} /></>
  if (summary.isError && !summary.data) return <ErrorState title="Dashboard summary is unavailable" error={summary.error} onRetry={() => void summary.refetch()} />
  const data = summary.data
  if (!data) return null
  const activity = (data.recent_activity || []).map((item) => ({id: item.id, time: item.created_at, type: item.event_type, title: item.event_type.replaceAll('.', ' '), detail: `${item.actor} · ${item.aggregate_type} ${item.aggregate_id}`}))
  const attention = data.attention || []
  const exposure = series.data?.exposure || []

  return <div className="page-stack">
    <PageHeader eyebrow="Portfolio command center" title={`Good overview${portfolio ? `, ${portfolio.name}` : ''}`} description="Monitor capital, execution, and the operating conditions that can block new risk." actions={<Freshness updatedAt={summary.dataUpdatedAt} stale={summary.isStale} fetching={summary.isFetching} onRefresh={() => void summary.refetch()} />} />
    {summary.isError && <ErrorState title="Some dashboard data may be stale" error={summary.error} onRetry={() => void summary.refetch()} compact />}
    <section className="operating-strip" aria-label="Operating status">
      <div><span>Environment</span><StatusBadge status={data.mode || 'PAPER'} /></div>
      <div><span>IBKR</span><StatusBadge status={data.gateway?.connected ? 'CONNECTED' : 'DISCONNECTED'} /></div>
      <div><span>Reconciliation</span><StatusBadge status={data.reconciliation_status} /></div>
      <div><span>Portfolio</span><strong>{data.portfolio?.name || 'Not selected'}</strong></div>
    </section>
    <section className="metric-grid" aria-label="Portfolio metrics">
      <MetricCard label="Net asset value" value={formatMoney(data.nav, data.account?.base_currency)} icon={<Landmark />} helper="Broker-reported" />
      <MetricCard label="Available cash" value={formatMoney(data.cash, data.account?.base_currency)} icon={<Banknote />} helper="After broker updates" />
      <MetricCard label="Buying power" value={formatMoney(data.buying_power, data.account?.base_currency)} icon={<CircleDollarSign />} />
      <MetricCard label="Daily P&L" value={formatMoney(data.daily_pnl, data.account?.base_currency)} icon={<Activity />} trend={Number(data.daily_pnl) > 0 ? 'positive' : Number(data.daily_pnl) < 0 ? 'negative' : 'neutral'} />
      <MetricCard label="Gross exposure" value={formatMoney(data.gross_exposure, data.account?.base_currency)} icon={<Scale />} />
      <MetricCard label="Active strategies" value={formatNumber(data.active_strategies)} icon={<Bot />} />
      <MetricCard label="Open orders" value={formatNumber(data.open_orders)} icon={<ShoppingCart />} />
      <MetricCard label="Attention items" value={formatNumber(attention.length)} icon={<AlertTriangle />} trend={attention.some((item) => item.severity === 'CRITICAL') ? 'negative' : 'neutral'} />
    </section>
    <div className="dashboard-grid">
      <Panel title="NAV & portfolio P&L" description={`Persisted portfolio observations · ${series.data?.source || 'waiting for data'}`} className="dashboard-chart">
        {series.isError ? <ErrorState error={series.error} onRetry={() => void series.refetch()} compact /> : series.isLoading ? <Skeleton height={270} /> : <TimeSeriesChart height={270} ariaLabel="Portfolio NAV and P&L chart" lines={[
          {name: 'NAV', data: series.data?.nav || [], color: '#4676f2', type: 'area'},
          {name: 'P&L', data: series.data?.pnl || [], color: '#0d9488'},
        ]} />}
      </Panel>
      <Panel title="Exposure" description="Gross and net marked exposure from real portfolio and market records">
        {series.isError ? <ErrorState error={series.error} compact /> : <TimeSeriesChart height={270} ariaLabel="Portfolio exposure chart" lines={[
          {name: 'Gross', data: exposure.map((point) => ({time: point.time, value: point.gross})), color: '#8b5cf6'},
          {name: 'Net', data: exposure.map((point) => ({time: point.time, value: point.net})), color: '#4676f2'},
        ]} />}
      </Panel>
      <Panel title="Recent activity" description="Latest persisted audit events"><ActivityTimeline items={activity} /></Panel>
      <Panel title="Needs attention" description="Conditions that may affect strategy or execution readiness">
        {attention.length ? <ul className="attention-list">{attention.map((item) => <li key={item.id}><StatusBadge status={item.severity} /><div><strong>{item.title}</strong><p>{item.detail}</p></div></li>)}</ul> : <div className="healthy-callout"><StatusBadge status="HEALTHY" /><div><strong>No immediate operator action</strong><p>Gateway, reconciliation, and recent risk checks show no active attention items.</p></div></div>}
      </Panel>
    </div>
  </div>
}
