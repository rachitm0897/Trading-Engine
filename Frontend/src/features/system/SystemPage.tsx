import {useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {ExternalLink, Power, RefreshCw, ShieldAlert} from 'lucide-react'
import {mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {AuditEvent, ReconciliationBreak, ReconciliationRun, RiskDecision, StreamMetric} from '../../api/types'
import {ActivityTimeline} from '../../components/ActivityTimeline'
import {CollapsibleSection, ConfirmActionDialog, DataTable, ErrorState, Freshness, MetricCard, PageHeader, Panel, Skeleton, StatusBadge, formatCompact, formatDateTime, formatNumber} from '../../components/ui'

interface KillAction {enabled: boolean; title: string; confirm: string}

export function SystemPage() {
  const queryClient = useQueryClient()
  const system = useQuery(queries.system())
  const gateway = useQuery(queries.gateway())
  const streaming = useQuery(queries.streaming())
  const reconciliation = useQuery(queries.reconciliation())
  const risk = useQuery(queries.risk())
  const audit = useQuery(queries.audit({limit: 250}))
  const [killAction, setKillAction] = useState<KillAction | null>(null)
  const gatewayUrl = (import.meta.env.VITE_GATEWAY_PUBLIC_URL || 'http://localhost:8080').replace(/\/$/, '')

  const refresh = async () => {await Promise.all(['system', 'gateway', 'streaming', 'reconciliation', 'risk', 'audit'].map((key) => queryClient.invalidateQueries({queryKey: [key]})))}
  const reconnect = useMutation({mutationFn: () => request<unknown>('gateway/', mutationOptions('POST', {}, true)), onSuccess: refresh})
  const kill = useMutation({
    mutationFn: ({enabled, reason}: {enabled: boolean; reason: string}) => request<unknown>('risk/', mutationOptions('POST', {scope: 'GLOBAL', enabled, reason}, true)),
    onSuccess: async () => {setKillAction(null); await refresh()},
  })
  const globalSwitch = risk.data?.kill_switches.find((item) => item.scope === 'GLOBAL' && item.enabled)
  const newest = Math.max(system.dataUpdatedAt, gateway.dataUpdatedAt, streaming.dataUpdatedAt, reconciliation.dataUpdatedAt, risk.dataUpdatedAt, audit.dataUpdatedAt)

  const breakColumns = [
    {id: 'category', header: 'Category', cell: (item: ReconciliationBreak) => <strong>{item.category}</strong>},
    {id: 'severity', header: 'Severity', cell: (item: ReconciliationBreak) => <StatusBadge status={item.severity} />},
    {id: 'material', header: 'Material', cell: (item: ReconciliationBreak) => <StatusBadge status={item.material ? 'MATERIAL' : 'NON-MATERIAL'} />},
    {id: 'internal', header: 'Internal', cell: (item: ReconciliationBreak) => <code>{formatCompact(item.internal_value)}</code>},
    {id: 'broker', header: 'Broker', cell: (item: ReconciliationBreak) => <code>{formatCompact(item.broker_value)}</code>},
    {id: 'created', header: 'Created', cell: (item: ReconciliationBreak) => formatDateTime(item.created_at)},
  ]
  const runColumns = [
    {id: 'trigger', header: 'Trigger', cell: (item: ReconciliationRun) => item.trigger},
    {id: 'status', header: 'Status', cell: (item: ReconciliationRun) => <StatusBadge status={item.status} />},
    {id: 'started', header: 'Started', cell: (item: ReconciliationRun) => formatDateTime(item.started_at)},
    {id: 'completed', header: 'Completed', cell: (item: ReconciliationRun) => formatDateTime(item.completed_at)},
  ]
  const riskColumns = [
    {id: 'check', header: 'Check', cell: (item: RiskDecision) => <strong>{item.check_name}</strong>},
    {id: 'decision', header: 'Decision', cell: (item: RiskDecision) => <StatusBadge status={item.decision} />},
    {id: 'reason', header: 'Reason', cell: (item: RiskDecision) => item.reason},
    {id: 'quantity', header: 'Requested / approved', align: 'right' as const, cell: (item: RiskDecision) => <span className="mono">{formatNumber(item.requested_quantity)} / {formatNumber(item.approved_quantity)}</span>},
    {id: 'created', header: 'Time', cell: (item: RiskDecision) => formatDateTime(item.created_at)},
  ]
  const auditColumns = [
    {id: 'time', header: 'Time', cell: (item: AuditEvent) => formatDateTime(item.created_at)},
    {id: 'event', header: 'Event', cell: (item: AuditEvent) => <strong>{item.event_type}</strong>},
    {id: 'actor', header: 'Actor', cell: (item: AuditEvent) => item.actor},
    {id: 'aggregate', header: 'Aggregate', cell: (item: AuditEvent) => <code>{item.aggregate_type} · {item.aggregate_id}</code>},
    {id: 'data', header: 'Data', cell: (item: AuditEvent) => <code>{formatCompact(item.data)}</code>},
  ]

  return <div className="page-stack">
    <PageHeader eyebrow="Operations & safety" title="System" description="Gateway, streaming, reconciliation, risk, and audit controls consolidated for operators." actions={<Freshness updatedAt={newest} stale={system.isStale || gateway.isStale} fetching={system.isFetching || gateway.isFetching || streaming.isFetching} onRefresh={() => void refresh()} />} />
    <section className="metric-grid compact"><MetricCard label="Application mode" value={<StatusBadge status={system.data?.mode || 'UNKNOWN'} />} /><MetricCard label="IBKR connection" value={<StatusBadge status={gateway.data?.connected ? 'CONNECTED' : 'DISCONNECTED'} />} /><MetricCard label="Reconciliation" value={<StatusBadge status={gateway.data?.reconciled ? 'RECONCILED' : 'BLOCKED'} />} /><MetricCard label="Material breaks" value={formatNumber(system.data?.material_breaks)} /><MetricCard label="Global kill switch" value={<StatusBadge status={globalSwitch ? 'ENGAGED' : 'CLEAR'} />} /></section>
    <div className="system-sections">
      <CollapsibleSection title="Gateway & operator console" description="Broker session status and noVNC authentication access." defaultOpen badge={<StatusBadge status={gateway.data?.connected ? 'CONNECTED' : 'DISCONNECTED'} />}>
        {gateway.isLoading ? <Skeleton lines={3} /> : gateway.isError ? <ErrorState title="Gateway is unavailable" error={gateway.error} onRetry={() => void gateway.refetch()} compact /> : <div className="system-gateway"><dl className="detail-list columns"><div><dt>Connection</dt><dd><StatusBadge status={gateway.data?.connected ? 'CONNECTED' : 'DISCONNECTED'} /></dd></div><div><dt>Broker mode</dt><dd><StatusBadge status={gateway.data?.mode || 'UNKNOWN'} /></dd></div><div><dt>Reconciliation</dt><dd><StatusBadge status={gateway.data?.reconciled ? 'RECONCILED' : 'PENDING'} /></dd></div><div><dt>Last callback</dt><dd>{formatDateTime(gateway.data?.last_callback)}</dd></div><div><dt>Worker</dt><dd><code>{gateway.data?.worker || '—'}</code></dd></div></dl><div className="system-actions"><button className="button-secondary" disabled={reconnect.isPending} onClick={() => reconnect.mutate()}><RefreshCw />{reconnect.isPending ? 'Requesting…' : 'Reconnect session'}</button><a className="button-primary" href={`${gatewayUrl}/novnc/vnc.html`} target="_blank" rel="noreferrer">Open noVNC<ExternalLink /></a></div><p className="inline-note">noVNC is only for IBKR login, 2FA, and Gateway settings. Broker credentials and raw TWS ports are not exposed here.</p></div>}
      </CollapsibleSection>
      <CollapsibleSection title="Streaming" description="Kafka delivery, Flink jobs, stale prices, and dead letters." badge={<StatusBadge status={streaming.data?.kafka_enabled ? streaming.data.flink.status || 'ENABLED' : 'DISABLED'} />}>
        {streaming.isLoading ? <Skeleton lines={4} /> : streaming.isError ? <ErrorState error={streaming.error} onRetry={() => void streaming.refetch()} compact /> : <div className="page-stack"><section className="metric-grid compact"><MetricCard label="Kafka" value={<StatusBadge status={streaming.data?.kafka_enabled ? 'ENABLED' : 'DISABLED'} />} /><MetricCard label="Outbox pending" value={formatNumber(streaming.data?.outbox_pending)} /><MetricCard label="Dead letters" value={formatNumber(streaming.data?.dead_letter_count)} /><MetricCard label="Stale instruments" value={formatNumber(streaming.data?.stale_instrument_count)} /></section><DataTable rows={streaming.data?.metrics || []} columns={streamColumns} getRowKey={(item) => item.id || `${item.component}-${item.metric}`} emptyTitle="No stream health metrics" /><div><h3>Flink jobs</h3>{(streaming.data?.flink.jobs || []).length ? <ul className="job-list">{(streaming.data?.flink.jobs || []).map((job, index) => <li key={String(job.id || job.name || index)}><strong>{String(job.name || job.id || `Job ${index + 1}`)}</strong><StatusBadge status={String(job.state || 'UNKNOWN')} /></li>)}</ul> : <div className="empty-inline">No Flink job data is currently available.</div>}</div></div>}
      </CollapsibleSection>
      <CollapsibleSection title="Reconciliation" description="Broker comparison runs and unresolved breaks." badge={<StatusBadge status={(reconciliation.data?.breaks || []).some((item) => item.material) ? 'MATERIAL BREAK' : 'CLEAR'} />}>
        {reconciliation.isError ? <ErrorState error={reconciliation.error} onRetry={() => void reconciliation.refetch()} compact /> : <div className="page-stack"><h3>Unresolved breaks</h3><DataTable rows={reconciliation.data?.breaks || []} columns={breakColumns} getRowKey={(item) => item.id} emptyTitle="No unresolved breaks" /><h3>Recent runs</h3><DataTable rows={reconciliation.data?.runs || []} columns={runColumns} getRowKey={(item) => item.id} emptyTitle="No reconciliation runs" /></div>}
      </CollapsibleSection>
      <CollapsibleSection title="Risk & kill switch" description="Pre-trade decisions and global trading halt control." badge={<StatusBadge status={globalSwitch ? 'ENGAGED' : 'CLEAR'} />}>
        <div className="danger-zone"><div><ShieldAlert /><div><strong>Global trading halt</strong><p>Requires a reason and explicit confirmation. This control does not weaken any account, portfolio, or strategy-level checks.</p></div></div>{globalSwitch ? <button className="button-secondary" onClick={() => setKillAction({enabled: false, title: 'Release global kill switch?', confirm: 'Release kill switch'})}><Power />Release</button> : <button className="button-danger" onClick={() => setKillAction({enabled: true, title: 'Confirm global trading halt', confirm: 'Engage kill switch'})}><ShieldAlert />Engage global</button>}</div>
        {risk.isError ? <ErrorState error={risk.error} onRetry={() => void risk.refetch()} compact /> : <DataTable rows={risk.data?.decisions || []} columns={riskColumns} getRowKey={(item) => item.id} emptyTitle="No risk decisions" />}
      </CollapsibleSection>
      <CollapsibleSection title="Audit log" description="Persisted operator, strategy, OMS, and broker facts.">
        {audit.isError ? <ErrorState error={audit.error} onRetry={() => void audit.refetch()} compact /> : <DataTable rows={audit.data || []} columns={auditColumns} getRowKey={(item) => item.id} emptyTitle="No audit events" />}
      </CollapsibleSection>
    </div>
    <ConfirmActionDialog open={Boolean(killAction)} title={killAction?.title || ''} description={killAction?.enabled ? 'New executable actions will be rejected across the platform. Existing broker state still requires monitoring and reconciliation.' : 'Releasing the global switch restores eligibility checks; it does not submit or resume orders automatically.'} confirmLabel={killAction?.confirm || 'Confirm'} pending={kill.isPending} danger={Boolean(killAction?.enabled)} onClose={() => setKillAction(null)} onConfirm={(reason) => {if (killAction) kill.mutate({enabled: killAction.enabled, reason})}} />
  </div>
}

const streamColumns = [
  {id: 'component', header: 'Component', cell: (item: StreamMetric) => item.component},
  {id: 'metric', header: 'Metric', cell: (item: StreamMetric) => <strong>{item.metric}</strong>},
  {id: 'status', header: 'Status', cell: (item: StreamMetric) => <StatusBadge status={item.status} />},
  {id: 'value', header: 'Value', cell: (item: StreamMetric) => <code>{formatCompact(item.value)}</code>},
  {id: 'time', header: 'Observed', cell: (item: StreamMetric) => formatDateTime(item.observed_at)},
]
