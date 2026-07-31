import {useMemo, useState} from 'react'
import {useMutation, useQuery, useQueryClient, type UseQueryResult} from '@tanstack/react-query'
import {ArrowLeft, CirclePause, Power, RefreshCw, SlidersHorizontal, Trash2} from 'lucide-react'
import {Link, useNavigate, useParams, useSearchParams} from 'react-router-dom'
import {mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {StrategyChartData, StrategyInstance, StrategyTimelineItem} from '../../api/types'
import {ActivityTimeline} from '../../components/ActivityTimeline'
import {TerminalChart, type ChartLine, type ChartMarker} from '../../components/charts/TerminalChart'
import {ConfirmActionDialog, DataTable, DeleteStrategyDialog, EmptyState, ErrorState, Freshness, PageHeader, Skeleton, StatusBadge, TerminalMetric, TerminalPanel, formatCompact, formatDateTime, formatNumber, formatPercent} from '../../components/ui'
import {canEnable, canFlatten, canPause, refreshAfterStrategyDeletion} from './strategyActions'

const tabs = ['Overview', 'Chart', 'Activity', 'Configuration', 'Advanced'] as const
type Tab = typeof tabs[number]

export function StrategyDetailPage() {
  const {strategyId = ''} = useParams()
  const id = Number(strategyId)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const requestedTab = searchParams.get('tab')
  const tab: Tab = tabs.find((item) => item.toLowerCase() === requestedTab?.toLowerCase()) || 'Overview'
  const [flattenOpen, setFlattenOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const strategy = useQuery(queries.strategy(id))
  const timeline = useQuery({...queries.strategyTimeline(id), enabled: id > 0 && (tab === 'Overview' || tab === 'Activity')})
  const chart = useQuery({...queries.strategyChart(id), enabled: id > 0 && (tab === 'Overview' || tab === 'Chart')})
  const action = useMutation({
    mutationFn: ({name, reason, retryKey}: {name: 'enable' | 'pause' | 'flatten'; reason?: string; retryKey?: string}) => {
      const options = mutationOptions(
        'POST',
        reason ? {reason, event_id: `operator-${name}-${crypto.randomUUID()}`} : {},
        true,
        retryKey,
      )
      if (retryKey) {
        const headers = new Headers(options.headers)
        headers.set('Idempotency-Retry', 'true')
        options.headers = headers
      }
      return request<unknown>(`strategy-instances/${id}/${name}/`, options)
    },
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
  const deleteAction = useMutation({
    mutationFn: (name: string) => request<{id: number}>(`strategy-instances/${id}/`, mutationOptions('DELETE', {strategy_name: name}, true)),
    onSuccess: async () => {
      setDeleteOpen(false)
      navigate('/strategies', {replace: true})
      await refreshAfterStrategyDeletion(queryClient, id)
    },
  })

  if (!Number.isFinite(id)) return <ErrorState title="Invalid strategy link" error={new Error('The strategy identifier is not valid.')} />
  if (strategy.isLoading) return <><PageHeader title="Strategy" description="Loading strategy state and immutable configuration…" /><Skeleton lines={7} height={500} /></>
  if (strategy.isError || !strategy.data) return <ErrorState title="Strategy not found" error={strategy.error} onRetry={() => void strategy.refetch()} />
  const item = strategy.data

  return <div className="page-stack">
    <PageHeader eyebrow={`${item.portfolio} / ${item.symbol}`} title={item.name} description={`${item.definition_name} · ${item.timeframe} · version ${item.version}`} actions={<><Freshness updatedAt={strategy.dataUpdatedAt} stale={strategy.isStale} fetching={strategy.isFetching} onRefresh={() => void strategy.refetch()} /><Link className="button-secondary" to="/strategies"><ArrowLeft />All strategies</Link></>} />
    <div className="strategy-control-bar"><div><StatusBadge status={item.enabled ? 'ENABLED' : 'DISABLED'} /><StatusBadge status={item.execution_mode} /><StatusBadge status={item.state} /><StatusBadge status={item.execution_workflow?.status || 'UNKNOWN'} />{item.conid ? <StatusBadge status="CONTRACT QUALIFIED" /> : <StatusBadge status="CONTRACT PENDING" />}</div><div><button className="button-secondary" disabled={!canEnable(item) || item.activation_operation?.status === 'FAILED' || action.isPending || deleteAction.isPending} onClick={() => action.mutate({name: 'enable'})}><Power />Enable</button>{item.activation_operation?.status === 'FAILED' && item.activation_operation.retryable && <button className="button-secondary" disabled={action.isPending || deleteAction.isPending} onClick={() => action.mutate({name: 'enable', retryKey: item.activation_operation!.idempotency_key})}><RefreshCw />Retry activation</button>}<button className="button-secondary" disabled={!canPause(item) || action.isPending || deleteAction.isPending} onClick={() => action.mutate({name: 'pause'})}><CirclePause />Pause</button><button className="button-danger-subtle" aria-label={`Delete ${item.name}`} disabled={action.isPending || deleteAction.isPending} onClick={() => setDeleteOpen(true)}><Trash2 />Delete</button><button className="button-danger-subtle" disabled={!canFlatten(item) || action.isPending || deleteAction.isPending} onClick={() => setFlattenOpen(true)}><SlidersHorizontal />Flatten target</button></div></div>
    {item.block_reason && <div className="inline-warning"><StatusBadge status="BLOCKED" /><div><strong>Strategy is not ready</strong><p>{item.block_reason}</p><p>Backend retryable: {item.activation_operation?.retryable ? 'Yes' : 'No'}</p></div></div>}
    {action.isError && <ErrorState title="Strategy action failed" error={action.error} compact />}
    {deleteAction.isError && <ErrorState title="Strategy deletion blocked" error={deleteAction.error} compact />}
    <div className="tabs" role="tablist" aria-label="Strategy details">{tabs.map((name) => <button key={name} role="tab" aria-selected={tab === name} className={tab === name ? 'active' : ''} onClick={() => setSearchParams({tab: name.toLowerCase()})}>{name}</button>)}</div>
    {tab === 'Overview' && <OverviewTab strategy={item} timeline={timeline.data || []} timelineLoading={timeline.isLoading} chart={chart} />}
    {tab === 'Chart' && <ChartTab query={chart} />}
    {tab === 'Activity' && <ActivityTab query={timeline} />}
    {tab === 'Configuration' && <ConfigurationTab strategy={item} />}
    {tab === 'Advanced' && <AdvancedTab strategy={item} />}
    <ConfirmActionDialog open={flattenOpen} title={`Flatten ${item.name}?`} description="This records a zero target for this strategy’s attributed exposure. It does not place an order directly." confirmLabel="Create flat target" pending={action.isPending} onClose={() => setFlattenOpen(false)} onConfirm={(reason) => action.mutate({name: 'flatten', reason})} />
    <DeleteStrategyDialog open={deleteOpen} strategyName={item.name} pending={deleteAction.isPending} onClose={() => setDeleteOpen(false)} onConfirm={() => deleteAction.mutate(item.name)} />
  </div>
}

function OverviewTab({strategy, timeline, timelineLoading, chart}: {strategy: StrategyInstance; timeline: StrategyTimelineItem[]; timelineLoading: boolean; chart: UseQueryResult<StrategyChartData, Error>}) {
  const warmup = strategy.warmup_required ? Math.min(1, strategy.warmup_progress / strategy.warmup_required) : 1
  return <div className="page-stack">
    <section className="workflow-summary" aria-label="Automatic execution workflow">
      <div><span>Workflow</span><StatusBadge status={strategy.execution_workflow?.status || 'UNKNOWN'} /></div>
      <div><span>Current stage</span><strong>{strategy.execution_workflow?.current_stage?.replaceAll('_', ' ') || 'Created'}</strong></div>
      <div><span>Trace ID</span><code>{strategy.execution_workflow?.trace_id || 'Not available'}</code></div>
      <div><span>Polling</span><strong>{strategy.execution_workflow?.terminal ? 'Stopped at terminal state' : strategy.execution_workflow?.active ? 'Every second' : 'Every 12 seconds'}</strong></div>
    </section>
    <section className="metric-grid compact">
      <TerminalMetric label="Latest signal" value={strategy.latest_signal || 'No signal'} helper={strategy.last_final_bar ? `Final bar ${formatDateTime(strategy.last_final_bar)}` : 'Awaiting a final bar'} />
      <TerminalMetric label="Current target" value={formatPercent(strategy.current_target)} helper="Strategy-attributed target" />
      <TerminalMetric label="Attributed quantity" value={<span className="mono">{formatNumber(strategy.attributed_quantity)}</span>} helper="Ledger-derived" />
      <TerminalMetric label="Active order" value={strategy.active_order ? <code>{strategy.active_order.slice(0, 12)}</code> : 'None'} helper={strategy.last_fill ? `Last fill ${strategy.last_fill}` : 'No recent fill'} />
    </section>
    <div className="detail-grid">
      <TerminalPanel id="execution-price" title="Execution price" description="Persisted price provenance and execution freshness"><dl className="detail-list"><div><dt>Price</dt><dd className="mono">{formatNumber(strategy.current_price?.value)}</dd></div><div><dt>Provider</dt><dd><StatusBadge status={strategy.current_price?.provider || 'UNKNOWN'} /></dd></div><div><dt>Data kind</dt><dd><StatusBadge status={strategy.current_price?.data_kind || 'UNKNOWN'} /></dd></div><div><dt>Source</dt><dd>{strategy.current_price?.source || 'Unknown'}</dd></div><div><dt>Timestamp</dt><dd>{formatDateTime(strategy.current_price?.timestamp)}</dd></div><div><dt>Fresh for execution</dt><dd><StatusBadge status={strategy.current_price?.fresh_for_execution ? 'FRESH' : 'NOT FRESH'} /></dd></div></dl></TerminalPanel>
      <TerminalPanel id="readiness" title="Readiness" description="Contract, subscription, and persisted streaming progress"><dl className="detail-list"><div><dt>Enabled</dt><dd><StatusBadge status={strategy.enabled ? 'ENABLED' : 'DISABLED'} /></dd></div><div><dt>Activation</dt><dd><StatusBadge status={strategy.activation_status} /></dd></div><div><dt>Data path</dt><dd><StatusBadge status={strategy.streaming?.status || 'UNKNOWN'} /></dd></div><div><dt>Contract</dt><dd>{strategy.conid ? <><StatusBadge status="QUALIFIED" /><code>{strategy.conid}</code></> : <StatusBadge status="PENDING" />}</dd></div><div><dt>Subscription</dt><dd><StatusBadge status={strategy.streaming?.subscription_state || 'MISSING'} /></dd></div><div><dt>Active provider</dt><dd><StatusBadge status={strategy.streaming?.active_provider || 'NONE'} /></dd></div><div><dt>Warm-up</dt><dd>{!strategy.enabled && strategy.state === 'DISABLED' ? <StatusBadge status="DISABLED" /> : <div className="wide-progress"><span>{strategy.warmup_progress} / {strategy.warmup_required} bars</span><div><i style={{width: `${warmup * 100}%`}} /></div></div>}</dd></div><div><dt>Last raw event</dt><dd>{formatDateTime(strategy.streaming?.last_raw_event)}</dd></div><div><dt>Last canonical event</dt><dd>{formatDateTime(strategy.streaming?.last_canonical_event)}</dd></div><div><dt>Last final bar</dt><dd>{formatDateTime(strategy.last_final_bar)}</dd></div><div><dt>Last indicator</dt><dd>{formatDateTime(strategy.streaming?.last_indicator)}</dd></div><div><dt>Last strategy run</dt><dd>{formatDateTime(strategy.streaming?.last_strategy_run)}</dd></div><div><dt>State</dt><dd><StatusBadge status={strategy.state} /></dd></div><div><dt>Mode</dt><dd><StatusBadge status={strategy.execution_mode} /></dd></div>{strategy.block_reason && <div><dt>Block reason</dt><dd>{strategy.block_reason}</dd></div>}{strategy.streaming?.last_error && <div><dt>Last error</dt><dd>{strategy.streaming.last_error}</dd></div>}</dl></TerminalPanel>
      <TerminalPanel id="latest-indicators" title="Latest indicators" description="Values used by the strategy’s current input bindings">{Object.entries(strategy.latest_indicators).length ? <dl className="indicator-list">{Object.entries(strategy.latest_indicators).map(([name, value]) => <div key={name}><dt>{name.replaceAll('_', ' ')}</dt><dd className="mono">{formatNumber(value)}</dd></div>)}</dl> : <EmptyState title="Indicators are warming up" description="Persisted final indicator values will appear after the required inputs arrive." />}</TerminalPanel>
      <div className="detail-wide"><ChartTab query={chart} /></div>
      <TerminalPanel id="execution-timeline" title="Execution timeline" description={`One trace across activation, market data, strategy, target, rebalance, intent, order, broker command, and fill: ${strategy.execution_workflow?.trace_id || 'pending'}`} className="detail-wide">{timelineLoading ? <Skeleton lines={4} /> : <ActivityTimeline items={timeline.map(timelineItem)} />}</TerminalPanel>
    </div>
  </div>
}

function ChartTab({query}: {query: UseQueryResult<StrategyChartData, Error>}) {
  if (query.isLoading) return <TerminalPanel id="strategy-chart-loading" collapsible={false}><Skeleton height={420} /></TerminalPanel>
  if (query.isError || !query.data) return <ErrorState title="Strategy chart is unavailable" error={query.error} onRetry={() => void query.refetch()} />
  const grouped = new Map<string, ChartLine>()
  query.data.indicators.forEach((indicator) => {
    const existing = grouped.get(indicator.name) || {name: indicator.name, data: [], kind: 'indicator' as const}
    existing.data.push({time: indicator.time, value: Number(indicator.value)})
    grouped.set(indicator.name, existing)
  })
  const markers: ChartMarker[] = query.data.markers.map((marker) => ({time: marker.time, label: marker.label, kind: marker.type.toLowerCase() as ChartMarker['kind']}))
  return <TerminalPanel id="strategy-chart" title="Market, indicators & execution markers" description={`Source: ${query.data.source}. No production series is hardcoded.`}><div className="chart-legend"><span><i className="marker signal" />Signal</span><span><i className="marker target" />Target</span><span><i className="marker order" />Order</span><span><i className="marker fill" />Fill</span></div><TerminalChart id="strategy-price" height={460} defaultChartType="candlestick" candles={query.data.bars.map((bar) => ({time: bar.time, open: Number(bar.open), high: Number(bar.high), low: Number(bar.low), close: Number(bar.close), volume: Number(bar.volume)}))} lines={[...grouped.values()]} markers={markers} ariaLabel="Strategy price, indicator, signal, target, order, and fill chart" /></TerminalPanel>
}

function ActivityTab({query}: {query: UseQueryResult<StrategyTimelineItem[], Error>}) {
  if (query.isLoading) return <Skeleton lines={6} />
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  return <TerminalPanel id="complete-execution-timeline" title="Complete execution timeline" description="All automatic paper-execution stages in workflow order, including pending stages and concrete blockers"><ActivityTimeline items={(query.data || []).map(timelineItem)} /></TerminalPanel>
}

function timelineItem(item: StrategyTimelineItem) {
  if (item.stage) {
    const detail = [
      item.detail,
      item.blocker ? `Blocker: ${item.blocker}` : '',
      item.blocker ? `Retryable: ${item.retryable ? 'Yes' : 'No'}` : '',
      item.entity_type && item.entity_id ? `${item.entity_type} ${item.entity_id}` : '',
    ].filter(Boolean).join(' · ')
    return {
      id: item.entity_id || item.stage,
      time: item.occurred_at,
      type: item.stage,
      title: item.label || item.stage.replaceAll('_', ' '),
      detail,
      status: item.status,
    }
  }
  item.id ||= 0
  item.type ||= 'EVENT'
  return {id: item.id, time: item.time, type: item.type, title: item.type.replaceAll('_', ' '), detail: `${item.detail || ''}${item.version ? `${item.detail ? ' · ' : ''}Version ${item.version}` : ''}`, status: item.status}
}

function ConfigurationTab({strategy}: {strategy: StrategyInstance}) {
  return <div className="detail-grid"><TerminalPanel id="parameters" title="Parameters" description="Immutable version configuration"><dl className="configuration-list">{Object.entries(strategy.parameters).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><code>{formatCompact(value)}</code></dd></div>)}</dl></TerminalPanel><TerminalPanel id="target-configuration" title="Target configuration"><dl className="configuration-list">{Object.entries(strategy.target_configuration).map(([key, value]) => <div key={key}><dt>{key.replaceAll('_', ' ')}</dt><dd><code>{formatCompact(value)}</code></dd></div>)}</dl></TerminalPanel><TerminalPanel id="binding" title="Binding" className="detail-wide"><dl className="detail-list columns"><div><dt>Portfolio</dt><dd>{strategy.portfolio}</dd></div><div><dt>Instrument</dt><dd className="mono">{strategy.symbol} · {strategy.exchange}</dd></div><div><dt>Definition</dt><dd>{strategy.definition_name}</dd></div><div><dt>Timeframe</dt><dd className="mono">{strategy.timeframe}</dd></div><div><dt>Risk policy</dt><dd>{strategy.risk_policy_id || 'Platform default'}</dd></div><div><dt>Order policy</dt><dd>{strategy.order_policy_id || 'Platform default'}</dd></div></dl></TerminalPanel></div>
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
  return <div className="page-stack"><TerminalPanel id="immutable-versions" title="Immutable versions" defaultOpen={false}><DataTable rows={strategy.versions || []} columns={versionColumns} getRowKey={(item) => item.id} emptyTitle="No version history" /></TerminalPanel><TerminalPanel id="shared-inputs" title="Shared streaming inputs" description="Bindings are deduplicated by instrument, timeframe, input, and parameter hash" defaultOpen={false}><DataTable rows={strategy.requirements || []} columns={requirementColumns} getRowKey={(item) => item.identity_hash || `${item.name}-${JSON.stringify(item.parameters)}`} emptyTitle="No active input bindings" /></TerminalPanel></div>
}
