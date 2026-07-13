import {useMemo, useState} from 'react'
import {useMutation, useQuery, useQueryClient, type UseQueryResult} from '@tanstack/react-query'
import {ArrowLeft, CirclePause, Power, SlidersHorizontal} from 'lucide-react'
import {Link, useParams, useSearchParams} from 'react-router-dom'
import {mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {StrategyChartData, StrategyInstance, StrategyTimelineItem} from '../../api/types'
import {ActivityTimeline} from '../../components/ActivityTimeline'
import {TimeSeriesChart, type ChartLine, type ChartMarker} from '../../components/charts/TimeSeriesChart'
import {ConfirmActionDialog, DataTable, EmptyState, ErrorState, Freshness, MetricCard, PageHeader, Panel, Skeleton, StatusBadge, formatCompact, formatDateTime, formatNumber, formatPercent} from '../../components/ui'
import {canEnable, canFlatten, canPause} from './strategyActions'

const tabs = ['Overview', 'Chart', 'Activity', 'Configuration', 'Advanced'] as const
type Tab = typeof tabs[number]

export function StrategyDetailPage() {
  const {strategyId = ''} = useParams()
  const id = Number(strategyId)
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const tab: Tab = tabs.find((item) => item.toLowerCase() === requestedTab?.toLowerCase()) || 'Overview'
  const [flattenOpen, setFlattenOpen] = useState(false)
  const strategy = useQuery(queries.strategy(id))
  const timeline = useQuery({...queries.strategyTimeline(id), enabled: id > 0 && (tab === 'Overview' || tab === 'Activity')})
  const chart = useQuery({...queries.strategyChart(id), enabled: id > 0 && tab === 'Chart'})
  const action = useMutation({
    mutationFn: ({name, reason}: {name: 'enable' | 'pause' | 'flatten'; reason?: string}) => request<unknown>(`strategy-instances/${id}/${name}/`, mutationOptions('POST', reason ? {reason, event_id: `operator-${name}-${crypto.randomUUID()}`} : {}, true)),
    onSuccess: async () => {
      setFlattenOpen(false)
      await Promise.all([
        queryClient.invalidateQueries({queryKey: ['strategy-instance', id]}),
        queryClient.invalidateQueries({queryKey: ['strategy-instances']}),
        queryClient.invalidateQueries({queryKey: ['strategy-timeline', id]}),
        queryClient.invalidateQueries({queryKey: ['strategy-chart', id]}),
      ])
    },
  })

  if (!Number.isFinite(id)) return <ErrorState title="Invalid strategy link" error={new Error('The strategy identifier is not valid.')} />
  if (strategy.isLoading) return <><PageHeader title="Strategy" description="Loading strategy state and immutable configuration…" /><Skeleton lines={7} height={500} /></>
  if (strategy.isError || !strategy.data) return <ErrorState title="Strategy not found" error={strategy.error} onRetry={() => void strategy.refetch()} />
  const item = strategy.data

  return <div className="page-stack">
    <PageHeader eyebrow={`${item.portfolio} / ${item.symbol}`} title={item.name} description={`${item.definition_name} · ${item.timeframe} · version ${item.version}`} actions={<><Freshness updatedAt={strategy.dataUpdatedAt} stale={strategy.isStale} fetching={strategy.isFetching} onRefresh={() => void strategy.refetch()} /><Link className="button-secondary" to="/strategies"><ArrowLeft />All strategies</Link></>} />
    <div className="strategy-control-bar"><div><StatusBadge status={item.execution_mode} /><StatusBadge status={item.state} />{item.conid ? <StatusBadge status="CONTRACT QUALIFIED" /> : <StatusBadge status="CONTRACT PENDING" />}</div><div><button className="button-secondary" disabled={!canEnable(item) || action.isPending} onClick={() => action.mutate({name: 'enable'})}><Power />Enable</button><button className="button-secondary" disabled={!canPause(item) || action.isPending} onClick={() => action.mutate({name: 'pause'})}><CirclePause />Pause</button><button className="button-danger-subtle" disabled={!canFlatten(item) || action.isPending} onClick={() => setFlattenOpen(true)}><SlidersHorizontal />Flatten target</button></div></div>
    {item.block_reason && <div className="inline-warning"><StatusBadge status="BLOCKED" /><div><strong>Strategy is not ready</strong><p>{item.block_reason}</p></div></div>}
    {action.isError && <ErrorState title="Strategy action failed" error={action.error} compact />}
    <div className="tabs" role="tablist" aria-label="Strategy details">{tabs.map((name) => <button key={name} role="tab" aria-selected={tab === name} className={tab === name ? 'active' : ''} onClick={() => setSearchParams({tab: name.toLowerCase()})}>{name}</button>)}</div>
    {tab === 'Overview' && <OverviewTab strategy={item} timeline={timeline.data || []} timelineLoading={timeline.isLoading} />}
    {tab === 'Chart' && <ChartTab query={chart} />}
    {tab === 'Activity' && <ActivityTab query={timeline} />}
    {tab === 'Configuration' && <ConfigurationTab strategy={item} />}
    {tab === 'Advanced' && <AdvancedTab strategy={item} />}
    <ConfirmActionDialog open={flattenOpen} title={`Flatten ${item.name}?`} description="This records a zero target for this strategy’s attributed exposure. It does not place an order directly." confirmLabel="Create flat target" pending={action.isPending} onClose={() => setFlattenOpen(false)} onConfirm={(reason) => action.mutate({name: 'flatten', reason})} />
  </div>
}

function OverviewTab({strategy, timeline, timelineLoading}: {strategy: StrategyInstance; timeline: StrategyTimelineItem[]; timelineLoading: boolean}) {
  const warmup = strategy.warmup_required ? Math.min(1, strategy.warmup_progress / strategy.warmup_required) : 1
  return <div className="page-stack">
    <section className="metric-grid compact">
      <MetricCard label="Latest signal" value={strategy.latest_signal || 'No signal'} helper={strategy.last_final_bar ? `Final bar ${formatDateTime(strategy.last_final_bar)}` : 'Awaiting a final bar'} />
      <MetricCard label="Current target" value={formatPercent(strategy.current_target)} helper="Strategy-attributed target" />
      <MetricCard label="Attributed quantity" value={<span className="mono">{formatNumber(strategy.attributed_quantity)}</span>} helper="Ledger-derived" />
      <MetricCard label="Active order" value={strategy.active_order ? <code>{strategy.active_order.slice(0, 12)}</code> : 'None'} helper={strategy.last_fill ? `Last fill ${strategy.last_fill}` : 'No recent fill'} />
    </section>
    <div className="detail-grid">
      <Panel title="Readiness" description="Contract, subscription, and persisted streaming progress"><dl className="detail-list"><div><dt>Data path</dt><dd><StatusBadge status={strategy.streaming?.status || 'UNKNOWN'} /></dd></div><div><dt>Contract</dt><dd>{strategy.conid ? <><StatusBadge status="QUALIFIED" /><code>{strategy.conid}</code></> : <StatusBadge status="PENDING" />}</dd></div><div><dt>Subscription</dt><dd><StatusBadge status={strategy.streaming?.subscription_state || 'MISSING'} /></dd></div><div><dt>Warm-up</dt><dd><div className="wide-progress"><span>{strategy.warmup_progress} / {strategy.warmup_required} bars</span><div><i style={{width: `${warmup * 100}%`}} /></div></div></dd></div><div><dt>Last raw event</dt><dd>{formatDateTime(strategy.streaming?.last_raw_event)}</dd></div><div><dt>Last canonical event</dt><dd>{formatDateTime(strategy.streaming?.last_canonical_event)}</dd></div><div><dt>Last final bar</dt><dd>{formatDateTime(strategy.last_final_bar)}</dd></div><div><dt>Last indicator</dt><dd>{formatDateTime(strategy.streaming?.last_indicator)}</dd></div><div><dt>Last strategy run</dt><dd>{formatDateTime(strategy.streaming?.last_strategy_run)}</dd></div><div><dt>State</dt><dd><StatusBadge status={strategy.state} /></dd></div><div><dt>Mode</dt><dd><StatusBadge status={strategy.execution_mode} /></dd></div>{strategy.streaming?.last_error && <div><dt>Last error</dt><dd>{strategy.streaming.last_error}</dd></div>}</dl></Panel>
      <Panel title="Latest indicators" description="Values used by the strategy’s current input bindings">{Object.entries(strategy.latest_indicators).length ? <dl className="indicator-list">{Object.entries(strategy.latest_indicators).map(([name, value]) => <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd className="mono">{formatNumber(value)}</dd></div>)}</dl> : <EmptyState title="Indicators are warming up" description="Persisted final indicator values will appear after the required inputs arrive." />}</Panel>
      <Panel title="Execution timeline" description="Recent signal-to-target and order-intent trace" className="detail-wide">{timelineLoading ? <Skeleton lines={4} /> : <ActivityTimeline items={timeline.slice(0, 8).map(timelineItem)} />}</Panel>
    </div>
  </div>
}

function ChartTab({query}: {query: UseQueryResult<StrategyChartData, Error>}) {
  if (query.isLoading) return <Panel><Skeleton height={420} /></Panel>
  if (query.isError || !query.data) return <ErrorState title="Strategy chart is unavailable" error={query.error} onRetry={() => void query.refetch()} />
  const grouped = new Map<string, ChartLine>()
  query.data.indicators.forEach((indicator) => {
    const existing = grouped.get(indicator.name) || {name: indicator.name, data: []}
    existing.data.push({time: indicator.time, value: Number(indicator.value)})
    grouped.set(indicator.name, existing)
  })
  const markers: ChartMarker[] = query.data.markers.map((marker) => ({time: marker.time, label: marker.label, kind: marker.type.toLowerCase() as ChartMarker['kind']}))
  return <Panel title="Market, indicators & execution markers" description={`Source: ${query.data.source}. No production series is hardcoded.`}><div className="chart-legend"><span><i className="marker signal" />Signal</span><span><i className="marker target" />Target</span><span><i className="marker order" />Order</span><span><i className="marker fill" />Fill</span></div><TimeSeriesChart height={420} candles={query.data.bars.map((bar) => ({time: bar.time, open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close)}))} lines={[...grouped.values()]} markers={markers} ariaLabel="Strategy price, indicator, signal, target, order, and fill chart" /></Panel>
}

function ActivityTab({query}: {query: UseQueryResult<StrategyTimelineItem[], Error>}) {
  if (query.isLoading) return <Skeleton lines={6} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  return <Panel title="Complete execution timeline" description="Runs, signals, targets, order intents, orders, and fills in reverse chronological order"><ActivityTimeline items={(query.data || []).map(timelineItem)} /></Panel>
}

function timelineItem(item: StrategyTimelineItem) {
  return {id: item.id, time: item.time, type: item.type, title: item.type.replaceAll('_', ' '), detail: `${item.detail || ''}${item.version ? `${item.detail ? ' · ' : ''}Version ${item.version}` : ''}`, status: item.status}
}

function ConfigurationTab({strategy}: {strategy: StrategyInstance}) {
  return <div className="detail-grid"><Panel title="Parameters" description="Immutable version configuration"><dl className="configuration-list">{Object.entries(strategy.parameters).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><code>{formatCompact(value)}</code></dd></div>)}</dl></Panel><Panel title="Target configuration"><dl className="configuration-list">{Object.entries(strategy.target_configuration).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><code>{formatCompact(value)}</code></dd></div>)}</dl></Panel><Panel title="Binding" className="detail-wide"><dl className="detail-list columns"><div><dt>Portfolio</dt><dd>{strategy.portfolio}</dd></div><div><dt>Instrument</dt><dd className="mono">{strategy.symbol} · {strategy.exchange}</dd></div><div><dt>Definition</dt><dd>{strategy.definition_name}</dd></div><div><dt>Timeframe</dt><dd className="mono">{strategy.timeframe}</dd></div><div><dt>Risk policy</dt><dd>{strategy.risk_policy_id || 'Platform default'}</dd></div><div><dt>Order policy</dt><dd>{strategy.order_policy_id || 'Platform default'}</dd></div></dl></Panel></div>
}

function AdvancedTab({strategy}: {strategy: StrategyInstance}) {
  const versionColumns = [
    {id: 'version', header: 'Version', cell: (item: NonNullable<StrategyInstance['versions']>[number]) => <strong>v{item.version}</strong>},
    {id: 'hash', header: 'Parameter hash', cell: (item: NonNullable<StrategyInstance['versions']>[number]) => <code>{item.parameter_hash.slice(0, 16)}…</code>},
    {id: 'created', header: 'Created', cell: (item: NonNullable<StrategyInstance['versions']>[number]) => formatDateTime(item.created_at)},
    {id: 'activated', header: 'Activated', cell: (item: NonNullable<StrategyInstance['versions']>[number]) => formatDateTime(item.activated_at)},
    {id: 'retired', header: 'Retired', cell: (item: NonNullable<StrategyInstance['versions']>[number]) => formatDateTime(item.retired_at)},
  ]
  const requirementColumns = [
    {id: 'type', header: 'Type', cell: (item: NonNullable<StrategyInstance['requirements']>[number]) => <StatusBadge status={item.input_type} />},
    {id: 'name', header: 'Input', cell: (item: NonNullable<StrategyInstance['requirements']>[number]) => <strong>{item.name}</strong>},
    {id: 'parameters', header: 'Parameters', cell: (item: NonNullable<StrategyInstance['requirements']>[number]) => <code>{formatCompact(item.parameters)}</code>},
    {id: 'warmup', header: 'Warm-up', align: 'right' as const, cell: (item: NonNullable<StrategyInstance['requirements']>[number]) => item.warmup_bars},
    {id: 'shared', header: 'Shared by', align: 'right' as const, cell: (item: NonNullable<StrategyInstance['requirements']>[number]) => item.shared_by ?? '—'},
    {id: 'active', header: 'State', cell: (item: NonNullable<StrategyInstance['requirements']>[number]) => <StatusBadge status={item.active ? 'ACTIVE' : 'INACTIVE'} />},
  ]
  return <div className="page-stack"><Panel title="Immutable versions"><DataTable rows={strategy.versions || []} columns={versionColumns} getRowKey={(item) => item.id} emptyTitle="No version history" /></Panel><Panel title="Shared streaming inputs" description="Bindings are deduplicated by instrument, timeframe, input, and parameter hash"><DataTable rows={strategy.requirements || []} columns={requirementColumns} getRowKey={(item) => item.identity_hash || `${item.name}-${JSON.stringify(item.parameters)}`} emptyTitle="No active input bindings" /></Panel></div>
}
