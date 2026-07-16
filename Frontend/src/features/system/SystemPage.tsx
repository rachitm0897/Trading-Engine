import {useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Database, ExternalLink, KeyRound, Power, RefreshCw, ShieldAlert} from 'lucide-react'
import {mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {AuditEvent, FinnhubProviderStatus, ReconciliationBreak, ReconciliationRun, RiskDecision, StrategyStreamStatus, StreamMetric} from '../../api/types'
import {ActivityTimeline} from '../../components/ActivityTimeline'
import {ConfirmActionDialog, DataTable, ErrorState, Freshness, PageHeader, Skeleton, StatusBadge, TerminalMetric, TerminalPanel, formatCompact, formatDateTime, formatNumber} from '../../components/ui'

interface KillAction {enabled: boolean; title: string; confirm: string}

export function SystemPage() {
  const queryClient = useQueryClient()
  const system = useQuery(queries.system())
  const gateway = useQuery(queries.gateway())
  const streaming = useQuery(queries.streaming())
  const reconciliation = useQuery(queries.reconciliation())
  const risk = useQuery(queries.risk())
  const audit = useQuery(queries.audit({limit: 250}))
  const finnhub = useQuery(queries.finnhub())
  const [killAction, setKillAction] = useState<KillAction | null>(null)
  const gatewayUrl = (import.meta.env.VITE_GATEWAY_PUBLIC_URL || 'http://localhost:8080').replace(/\/$/, '')

  const refresh = async () => {await Promise.all(['system', 'gateway', 'streaming', 'reconciliation', 'risk', 'audit', 'finnhub'].map((key) => queryClient.invalidateQueries({queryKey: [key]})))}
  const reconnect = useMutation({mutationFn: () => request<unknown>('gateway/', mutationOptions('POST', {}, true)), onSuccess: refresh})
  const kill = useMutation({
    mutationFn: ({enabled, reason}: {enabled: boolean; reason: string}) => request<unknown>('risk/', mutationOptions('POST', {scope: 'GLOBAL', enabled, reason}, true)),
    onSuccess: async () => {setKillAction(null); await refresh()},
  })
  const globalSwitch = risk.data?.kill_switches.find((item) => item.scope === 'GLOBAL' && item.enabled)
  const newest = Math.max(system.dataUpdatedAt, gateway.dataUpdatedAt, streaming.dataUpdatedAt, reconciliation.dataUpdatedAt, risk.dataUpdatedAt, audit.dataUpdatedAt, finnhub.dataUpdatedAt)

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
    <section className="metric-grid compact"><TerminalMetric label="Application mode" value={<StatusBadge status={system.data?.mode || 'UNKNOWN'} />} /><TerminalMetric label="IBKR connection" value={<StatusBadge status={gateway.data?.connected ? 'CONNECTED' : 'DISCONNECTED'} />} /><TerminalMetric label="Reconciliation" value={<StatusBadge status={gateway.data?.reconciled ? 'RECONCILED' : 'BLOCKED'} />} /><TerminalMetric label="Material breaks" value={formatNumber(system.data?.material_breaks)} /><TerminalMetric label="Global kill switch" value={<StatusBadge status={globalSwitch ? 'ENGAGED' : 'CLEAR'} />} /></section>
    <div className="system-sections">
      <TerminalPanel id="market-data-providers" title="Market data providers" description="Secure historical and reference-data credentials. Environment configuration is preferred by default." badge={<StatusBadge status={finnhub.data?.configured ? 'CONFIGURED' : 'NOT CONFIGURED'} />}>
        {finnhub.isLoading ? <Skeleton lines={4} /> : finnhub.isError ? <ErrorState title="Finnhub status is unavailable" error={finnhub.error} onRetry={() => void finnhub.refetch()} compact /> : <FinnhubPanel status={finnhub.data!} onChanged={() => queryClient.invalidateQueries({queryKey: ['finnhub']})} />}
      </TerminalPanel>
      <TerminalPanel id="gateway-console" title="Gateway & operator console" description="Broker session status and noVNC authentication access." badge={<StatusBadge status={gateway.data?.connected ? 'CONNECTED' : 'DISCONNECTED'} />}>
        {gateway.isLoading ? <Skeleton lines={3} /> : gateway.isError ? <ErrorState title="Gateway is unavailable" error={gateway.error} onRetry={() => void gateway.refetch()} compact /> : <div className="system-gateway"><dl className="detail-list columns"><div><dt>Connection</dt><dd><StatusBadge status={gateway.data?.connected ? 'CONNECTED' : 'DISCONNECTED'} /></dd></div><div><dt>Broker mode</dt><dd><StatusBadge status={gateway.data?.mode || 'UNKNOWN'} /></dd></div><div><dt>Reconciliation</dt><dd><StatusBadge status={gateway.data?.reconciled ? 'RECONCILED' : 'PENDING'} /></dd></div><div><dt>Last callback</dt><dd>{formatDateTime(gateway.data?.last_callback)}</dd></div><div><dt>Worker</dt><dd><code>{gateway.data?.worker || '—'}</code></dd></div></dl><div className="system-actions"><button className="button-secondary" disabled={reconnect.isPending} onClick={() => reconnect.mutate()}><RefreshCw />{reconnect.isPending ? 'Requesting…' : 'Reconnect session'}</button><a className="button-primary" href={`${gatewayUrl}/novnc/vnc.html`} target="_blank" rel="noreferrer">Open noVNC<ExternalLink /></a></div><p className="inline-note">noVNC is only for IBKR login, 2FA, and Gateway settings. Broker credentials and raw TWS ports are not exposed here.</p></div>}
      </TerminalPanel>
      <TerminalPanel id="streaming" title="Streaming" description="Gateway-to-strategy delivery, lag, jobs, persisted events, and errors." badge={<StatusBadge status={streaming.data?.data_path_status || 'UNKNOWN'} />} defaultOpen={false}>
        {streaming.isLoading ? <Skeleton lines={4} /> : streaming.isError ? <ErrorState error={streaming.error} onRetry={() => void streaming.refetch()} compact /> : <div className="page-stack"><section className="metric-grid compact"><TerminalMetric label="Data path" value={<StatusBadge status={streaming.data?.data_path_status || 'UNKNOWN'} />} /><TerminalMetric label="Gateway" value={<StatusBadge status={streaming.data?.gateway.status || 'UNKNOWN'} />} /><TerminalMetric label="Backend consumer" value={<StatusBadge status={streaming.data?.consumer.status || 'UNKNOWN'} />} helper={streaming.data?.consumer.last_heartbeat ? formatDateTime(streaming.data.consumer.last_heartbeat) : 'No heartbeat'} /><TerminalMetric label="Flink" value={<StatusBadge status={streaming.data?.flink.status || 'UNKNOWN'} />} /><TerminalMetric label="Outbox pending / failed" value={`${formatNumber(streaming.data?.outbox_pending)} / ${formatNumber(streaming.data?.outbox_failed)}`} /><TerminalMetric label="Dead letters" value={formatNumber(streaming.data?.dead_letter_count)} /><TerminalMetric label="Stale instruments" value={formatNumber(streaming.data?.stale_instrument_count)} /></section>{(streaming.data?.data_path_reasons || []).length ? <div className="inline-warning"><StatusBadge status="DEGRADED" /><div><strong>Streaming path is not healthy</strong><p>{streaming.data?.data_path_reasons.join(' · ')}</p></div></div> : null}<div><h3>Active strategy data paths</h3><DataTable rows={streaming.data?.strategies || []} columns={strategyStreamColumns} getRowKey={(item) => item.strategy_id} emptyTitle="No active strategy data paths" /></div><DataTable rows={streaming.data?.metrics || []} columns={streamColumns} getRowKey={(item) => item.id || `${item.component}-${item.metric}`} emptyTitle="No stream health metrics" /><div><h3>Flink jobs</h3>{(streaming.data?.flink.jobs || []).length ? <ul className="job-list">{(streaming.data?.flink.jobs || []).map((job, index) => <li key={String(job.id || job.name || index)}><strong>{String(job.name || job.id || `Job ${index + 1}`)}</strong><StatusBadge status={String(job.state || 'UNKNOWN')} /></li>)}</ul> : <div className="empty-inline">No Flink job data is currently available.</div>}</div></div>}
      </TerminalPanel>
      <TerminalPanel id="reconciliation" title="Reconciliation" description="Broker comparison runs and unresolved breaks." badge={<StatusBadge status={(reconciliation.data?.breaks || []).some((item) => item.material) ? 'MATERIAL BREAK' : 'CLEAR'} />} defaultOpen={false}>
        {reconciliation.isError ? <ErrorState error={reconciliation.error} onRetry={() => void reconciliation.refetch()} compact /> : <div className="page-stack"><h3>Unresolved breaks</h3><DataTable rows={reconciliation.data?.breaks || []} columns={breakColumns} getRowKey={(item) => item.id} emptyTitle="No unresolved breaks" /><h3>Recent runs</h3><DataTable rows={reconciliation.data?.runs || []} columns={runColumns} getRowKey={(item) => item.id} emptyTitle="No reconciliation runs" /></div>}
      </TerminalPanel>
      <TerminalPanel id="risk-kill-switch" title="Risk & kill switch" description="Pre-trade decisions and global trading halt control." badge={<StatusBadge status={globalSwitch ? 'ENGAGED' : 'CLEAR'} />}>
        <div className="danger-zone"><div><ShieldAlert /><div><strong>Global trading halt</strong><p>Requires a reason and explicit confirmation. This control does not weaken any account, portfolio, or strategy-level checks.</p></div></div>{globalSwitch ? <button className="button-secondary" onClick={() => setKillAction({enabled: false, title: 'Release global kill switch?', confirm: 'Release kill switch'})}><Power />Release</button> : <button className="button-danger" onClick={() => setKillAction({enabled: true, title: 'Confirm global trading halt', confirm: 'Engage kill switch'})}><ShieldAlert />Engage global</button>}</div>
        {risk.isError ? <ErrorState error={risk.error} onRetry={() => void risk.refetch()} compact /> : <DataTable rows={risk.data?.decisions || []} columns={riskColumns} getRowKey={(item) => item.id} emptyTitle="No risk decisions" />}
      </TerminalPanel>
      <TerminalPanel id="audit-log" title="Audit log" description="Persisted operator, strategy, OMS, and broker facts." className="system-wide" defaultOpen={false}>
        {audit.isError ? <ErrorState error={audit.error} onRetry={() => void audit.refetch()} compact /> : <DataTable rows={audit.data || []} columns={auditColumns} getRowKey={(item) => item.id} emptyTitle="No audit events" />}
      </TerminalPanel>
    </div>
    <ConfirmActionDialog open={Boolean(killAction)} title={killAction?.title || ''} description={killAction?.enabled ? 'New executable actions will be rejected across the platform. Existing broker state still requires monitoring and reconciliation.' : 'Releasing the global switch restores eligibility checks; it does not submit or resume orders automatically.'} confirmLabel={killAction?.confirm || 'Confirm'} pending={kill.isPending} danger={Boolean(killAction?.enabled)} onClose={() => setKillAction(null)} onConfirm={(reason) => {if (killAction) kill.mutate({enabled: killAction.enabled, reason})}} />
  </div>
}

function FinnhubPanel({status, onChanged}: {status: FinnhubProviderStatus; onChanged: () => Promise<unknown>}) {
  const [open, setOpen] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const save = useMutation({
    mutationFn: () => request<FinnhubProviderStatus>('data-providers/finnhub/configure/', mutationOptions('POST', {api_key: apiKey}, true)),
    onSettled: async () => {setApiKey(''); await onChanged()},
  })
  const test = useMutation({
    mutationFn: () => request<FinnhubProviderStatus>('data-providers/finnhub/test/', mutationOptions('POST', {symbol: 'AAPL', api_key: apiKey || undefined}, true)),
    onSettled: async () => {setApiKey(''); await onChanged()},
  })
  const close = () => {setApiKey(''); save.reset(); test.reset(); setOpen(false)}
  return <div className="page-stack">
    <section className="metric-grid compact">
      <TerminalMetric label="Finnhub" value={<StatusBadge status={status.configured && status.enabled ? 'READY' : 'NOT CONFIGURED'} />} icon={<Database />} />
      <TerminalMetric label="Effective source" value={status.effective_source} helper={status.masked_api_key || 'No key configured'} />
      <TerminalMetric label="Last successful request" value={formatDateTime(status.last_success_at)} />
      <TerminalMetric label="Rate limit remaining" value={status.rate_limit_state.remaining || '—'} helper={status.rate_limit_state.limit ? `Limit ${status.rate_limit_state.limit}` : undefined} />
    </section>
    {status.last_error && <div className="inline-warning"><StatusBadge status="ERROR" /><div><strong>Last provider error</strong><p>{status.last_error}</p></div></div>}
    <div className="system-actions"><button className="button-primary" onClick={() => setOpen(true)}><KeyRound />Configure Finnhub</button></div>
    {open && <div className="dialog-layer" role="presentation">
      <form className="confirm-dialog finnhub-dialog" role="dialog" aria-modal="true" aria-labelledby="finnhub-dialog-title" autoComplete="off" onSubmit={(event) => {event.preventDefault(); save.mutate()}}>
        <header><KeyRound /><div><h2 id="finnhub-dialog-title">Finnhub API key</h2><p>Test a transient key or encrypt and save it in the backend. The complete key is never returned.</p></div></header>
        <dl className="detail-list">
          <div><dt>Current configuration</dt><dd>{status.masked_api_key || 'No key configured'}</dd></div>
          <div><dt>Environment source</dt><dd><StatusBadge status={status.environment_configured ? (status.effective_source === 'ENVIRONMENT' ? 'ACTIVE' : 'CONFIGURED') : 'NOT CONFIGURED'} /></dd></div>
          <div><dt>Last successful test</dt><dd>{formatDateTime(status.last_test_success_at)}</dd></div>
          <div><dt>Last error</dt><dd>{status.last_error || 'None'}</dd></div>
        </dl>
        <label>Finnhub API key<input aria-label="Finnhub API key" type="password" value={apiKey} placeholder={status.masked_api_key || 'Enter a Finnhub key'} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" /></label>
        {status.environment_configured && <p className="inline-note">The environment key remains authoritative unless database override is explicitly enabled on the backend.</p>}
        {save.isError && <ErrorState title="Finnhub key was not saved" error={save.error} compact />}
        {test.isError && <ErrorState title="Finnhub key test failed" error={test.error} compact />}
        {test.data?.connected && <div className="inline-success"><StatusBadge status="CONNECTED" />Finnhub key test passed using the {(test.data.source || test.data.effective_source).toLowerCase()} credential.</div>}
        <footer><button type="button" className="button-quiet" onClick={close}>Close</button><button type="button" className="button-secondary" disabled={test.isPending || save.isPending} onClick={() => test.mutate()}><RefreshCw />{test.isPending ? 'Testing…' : 'Test key'}</button><button type="submit" className="button-primary" disabled={!apiKey.trim() || save.isPending || test.isPending}><KeyRound />{save.isPending ? 'Saving…' : 'Save key'}</button></footer>
      </form>
    </div>}
  </div>
}

const strategyStreamColumns = [
  {id: 'strategy', header: 'Strategy', cell: (item: StrategyStreamStatus) => <div className="primary-cell"><strong>{item.strategy}</strong><span>{item.symbol} · {item.timeframe} · conId {item.conid || 'missing'}</span></div>},
  {id: 'status', header: 'Path', cell: (item: StrategyStreamStatus) => <StatusBadge status={item.status} />},
  {id: 'subscription', header: 'Subscription', cell: (item: StrategyStreamStatus) => <StatusBadge status={item.subscription_state} />},
  {id: 'raw', header: 'Raw', cell: (item: StrategyStreamStatus) => formatDateTime(item.last_raw_event)},
  {id: 'canonical', header: 'Canonical / final', cell: (item: StrategyStreamStatus) => <div className="primary-cell"><span>{formatDateTime(item.last_canonical_event)}</span><span>{formatDateTime(item.last_final_bar)}</span></div>},
  {id: 'warmup', header: 'Warm-up', cell: (item: StrategyStreamStatus) => `${item.warmup_progress} / ${item.warmup_required}`},
  {id: 'evaluation', header: 'Indicator / run', cell: (item: StrategyStreamStatus) => <div className="primary-cell"><span>{formatDateTime(item.last_indicator)}</span><span>{formatDateTime(item.last_strategy_run)}</span></div>},
  {id: 'error', header: 'Last error', cell: (item: StrategyStreamStatus) => item.last_error || (item.missing.length ? `Waiting for ${item.missing.join(', ')}` : 'None')},
]

const streamColumns = [
  {id: 'component', header: 'Component', cell: (item: StreamMetric) => item.component},
  {id: 'metric', header: 'Metric', cell: (item: StreamMetric) => <strong>{item.metric}</strong>},
  {id: 'status', header: 'Status', cell: (item: StreamMetric) => <StatusBadge status={item.status} />},
  {id: 'value', header: 'Value', cell: (item: StreamMetric) => <code>{formatCompact(item.value)}</code>},
  {id: 'time', header: 'Observed', cell: (item: StreamMetric) => formatDateTime(item.observed_at)},
]
