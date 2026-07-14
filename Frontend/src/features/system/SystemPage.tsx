import {useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Database, ExternalLink, KeyRound, Power, RefreshCw, ShieldAlert} from 'lucide-react'
import {mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {AdminSession, AuditEvent, FinnhubProviderStatus, ReconciliationBreak, ReconciliationRun, RiskDecision, StrategyStreamStatus, StreamMetric} from '../../api/types'
import {ActivityTimeline} from '../../components/ActivityTimeline'
import {CollapsibleSection, ConfirmActionDialog, DataTable, ErrorState, Freshness, MetricCard, PageHeader, Panel, Skeleton, StatusBadge, formatCompact, formatDateTime, formatNumber} from '../../components/ui'

interface KillAction {enabled: boolean; title: string; confirm: string}

export function SystemPage() {
  const queryClient = useQueryClient()
  const auth = useQuery(queries.authSession())
  const system = useQuery(queries.system())
  const gateway = useQuery(queries.gateway())
  const streaming = useQuery(queries.streaming())
  const reconciliation = useQuery(queries.reconciliation())
  const risk = useQuery(queries.risk())
  const audit = useQuery(queries.audit({limit: 250}))
  const finnhub = useQuery(queries.finnhub())
  const [killAction, setKillAction] = useState<KillAction | null>(null)
  const gatewayUrl = (import.meta.env.VITE_GATEWAY_PUBLIC_URL || 'http://localhost:8080').replace(/\/$/, '')

  const refresh = async () => {await Promise.all(['auth-session', 'system', 'gateway', 'streaming', 'reconciliation', 'risk', 'audit', 'finnhub'].map((key) => queryClient.invalidateQueries({queryKey: [key]})))}
  const reconnect = useMutation({mutationFn: () => request<unknown>('gateway/', mutationOptions('POST', {}, true)), onSuccess: refresh})
  const kill = useMutation({
    mutationFn: ({enabled, reason}: {enabled: boolean; reason: string}) => request<unknown>('risk/', mutationOptions('POST', {scope: 'GLOBAL', enabled, reason}, true)),
    onSuccess: async () => {setKillAction(null); await refresh()},
  })
  const globalSwitch = risk.data?.kill_switches.find((item) => item.scope === 'GLOBAL' && item.enabled)
  const newest = Math.max(auth.dataUpdatedAt, system.dataUpdatedAt, gateway.dataUpdatedAt, streaming.dataUpdatedAt, reconciliation.dataUpdatedAt, risk.dataUpdatedAt, audit.dataUpdatedAt, finnhub.dataUpdatedAt)

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
      <CollapsibleSection title="Market data providers" description="Secure historical and reference-data credentials. Environment configuration is preferred by default." defaultOpen badge={<StatusBadge status={finnhub.data?.configured ? 'CONFIGURED' : 'NOT CONFIGURED'} />}>
        {!auth.isLoading && <AdminSessionPanel session={auth.data} onChanged={refresh} />}
        {finnhub.isLoading ? <Skeleton lines={4} /> : finnhub.isError ? <ErrorState title="Finnhub status is unavailable" error={finnhub.error} onRetry={() => void finnhub.refetch()} compact /> : <FinnhubPanel status={finnhub.data!} onChanged={() => queryClient.invalidateQueries({queryKey: ['finnhub']})} />}
      </CollapsibleSection>
      <CollapsibleSection title="Gateway & operator console" description="Broker session status and noVNC authentication access." defaultOpen badge={<StatusBadge status={gateway.data?.connected ? 'CONNECTED' : 'DISCONNECTED'} />}>
        {gateway.isLoading ? <Skeleton lines={3} /> : gateway.isError ? <ErrorState title="Gateway is unavailable" error={gateway.error} onRetry={() => void gateway.refetch()} compact /> : <div className="system-gateway"><dl className="detail-list columns"><div><dt>Connection</dt><dd><StatusBadge status={gateway.data?.connected ? 'CONNECTED' : 'DISCONNECTED'} /></dd></div><div><dt>Broker mode</dt><dd><StatusBadge status={gateway.data?.mode || 'UNKNOWN'} /></dd></div><div><dt>Reconciliation</dt><dd><StatusBadge status={gateway.data?.reconciled ? 'RECONCILED' : 'PENDING'} /></dd></div><div><dt>Last callback</dt><dd>{formatDateTime(gateway.data?.last_callback)}</dd></div><div><dt>Worker</dt><dd><code>{gateway.data?.worker || '—'}</code></dd></div></dl><div className="system-actions"><button className="button-secondary" disabled={reconnect.isPending} onClick={() => reconnect.mutate()}><RefreshCw />{reconnect.isPending ? 'Requesting…' : 'Reconnect session'}</button><a className="button-primary" href={`${gatewayUrl}/novnc/vnc.html`} target="_blank" rel="noreferrer">Open noVNC<ExternalLink /></a></div><p className="inline-note">noVNC is only for IBKR login, 2FA, and Gateway settings. Broker credentials and raw TWS ports are not exposed here.</p></div>}
      </CollapsibleSection>
      <CollapsibleSection title="Streaming" description="Gateway-to-strategy delivery, lag, jobs, persisted events, and errors." badge={<StatusBadge status={streaming.data?.data_path_status || 'UNKNOWN'} />}>
        {streaming.isLoading ? <Skeleton lines={4} /> : streaming.isError ? <ErrorState error={streaming.error} onRetry={() => void streaming.refetch()} compact /> : <div className="page-stack"><section className="metric-grid compact"><MetricCard label="Data path" value={<StatusBadge status={streaming.data?.data_path_status || 'UNKNOWN'} />} /><MetricCard label="Gateway" value={<StatusBadge status={streaming.data?.gateway.status || 'UNKNOWN'} />} /><MetricCard label="Backend consumer" value={<StatusBadge status={streaming.data?.consumer.status || 'UNKNOWN'} />} helper={streaming.data?.consumer.last_heartbeat ? formatDateTime(streaming.data.consumer.last_heartbeat) : 'No heartbeat'} /><MetricCard label="Flink" value={<StatusBadge status={streaming.data?.flink.status || 'UNKNOWN'} />} /><MetricCard label="Outbox pending / failed" value={`${formatNumber(streaming.data?.outbox_pending)} / ${formatNumber(streaming.data?.outbox_failed)}`} /><MetricCard label="Dead letters" value={formatNumber(streaming.data?.dead_letter_count)} /><MetricCard label="Stale instruments" value={formatNumber(streaming.data?.stale_instrument_count)} /></section>{(streaming.data?.data_path_reasons || []).length ? <div className="inline-warning"><StatusBadge status="DEGRADED" /><div><strong>Streaming path is not healthy</strong><p>{streaming.data?.data_path_reasons.join(' · ')}</p></div></div> : null}<div><h3>Active strategy data paths</h3><DataTable rows={streaming.data?.strategies || []} columns={strategyStreamColumns} getRowKey={(item) => item.strategy_id} emptyTitle="No active strategy data paths" /></div><DataTable rows={streaming.data?.metrics || []} columns={streamColumns} getRowKey={(item) => item.id || `${item.component}-${item.metric}`} emptyTitle="No stream health metrics" /><div><h3>Flink jobs</h3>{(streaming.data?.flink.jobs || []).length ? <ul className="job-list">{(streaming.data?.flink.jobs || []).map((job, index) => <li key={String(job.id || job.name || index)}><strong>{String(job.name || job.id || `Job ${index + 1}`)}</strong><StatusBadge status={String(job.state || 'UNKNOWN')} /></li>)}</ul> : <div className="empty-inline">No Flink job data is currently available.</div>}</div></div>}
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

function AdminSessionPanel({session, onChanged}: {session?: AdminSession; onChanged: () => Promise<void>}) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const login = useMutation({
    mutationFn: () => request<AdminSession>('auth/session/', mutationOptions('POST', {username, password})),
    onSuccess: async () => {setPassword(''); await onChanged()},
  })
  const logout = useMutation({
    mutationFn: () => request<AdminSession>('auth/session/', mutationOptions('DELETE')),
    onSuccess: onChanged,
  })
  if (session?.is_admin) return <div className="inline-note system-actions"><span>Signed in as administrator <strong>{session.username}</strong>.</span><button className="button-quiet" disabled={logout.isPending} onClick={() => logout.mutate()}>Sign out</button></div>
  return <div className="page-stack"><form className="form-grid three-columns" onSubmit={(event) => {event.preventDefault(); login.mutate()}}><label>Administrator username<input aria-label="Administrator username" value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required /></label><label>Administrator password<input aria-label="Administrator password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required /></label><button className="button-secondary form-submit" disabled={login.isPending}>{login.isPending ? 'Signing in…' : 'Sign in to manage providers'}</button></form>{login.isError && <ErrorState title="Administrator sign-in failed" error={login.error} compact />}</div>
}

function FinnhubPanel({status, onChanged}: {status: FinnhubProviderStatus; onChanged: () => Promise<unknown>}) {
  const [apiKey, setApiKey] = useState('')
  const [enabled, setEnabled] = useState(status.enabled)
  const [overrideEnvironment, setOverrideEnvironment] = useState(status.database_override_requested)
  const save = useMutation({
    mutationFn: () => request<FinnhubProviderStatus>('data-providers/finnhub/configure/', mutationOptions('POST', {api_key: apiKey || undefined, enabled, override_environment: overrideEnvironment}, true)),
    onSuccess: async () => {setApiKey(''); await onChanged()},
  })
  const test = useMutation({
    mutationFn: () => request<FinnhubProviderStatus>('data-providers/finnhub/test/', mutationOptions('POST', {symbol: 'AAPL'}, true)),
    onSuccess: onChanged,
  })
  return <div className="page-stack">
    <section className="metric-grid compact">
      <MetricCard label="Finnhub" value={<StatusBadge status={status.configured && status.enabled ? 'READY' : 'NOT CONFIGURED'} />} icon={<Database />} />
      <MetricCard label="Effective source" value={status.effective_source} helper={status.masked_api_key || 'No key configured'} />
      <MetricCard label="Last successful request" value={formatDateTime(status.last_success_at)} />
      <MetricCard label="Rate limit remaining" value={status.rate_limit_state.remaining || '—'} helper={status.rate_limit_state.limit ? `Limit ${status.rate_limit_state.limit}` : undefined} />
    </section>
    {status.last_error && <div className="inline-warning"><StatusBadge status="ERROR" /><div><strong>Last provider error</strong><p>{status.last_error}</p></div></div>}
    {status.can_manage ? <form className="form-grid three-columns" onSubmit={(event) => {event.preventDefault(); save.mutate()}} autoComplete="off">
      <label>Replace API key<input aria-label="Finnhub API key" type="password" value={apiKey} placeholder={status.masked_api_key || 'Enter a new Finnhub key'} onChange={(event) => setApiKey(event.target.value)} autoComplete="new-password" /></label>
      <label className="checkbox-field"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />Provider enabled</label>
      <label className="checkbox-field"><input type="checkbox" checked={overrideEnvironment} disabled={!status.database_override_allowed} onChange={(event) => setOverrideEnvironment(event.target.checked)} />Override environment key</label>
      <div className="system-actions form-submit"><button className="button-primary" disabled={save.isPending || (!apiKey && enabled === status.enabled && overrideEnvironment === status.database_override_requested)}><KeyRound />{save.isPending ? 'Saving…' : 'Save provider'}</button><button type="button" className="button-secondary" disabled={test.isPending || !status.configured || !status.enabled} onClick={() => test.mutate()}><RefreshCw />{test.isPending ? 'Testing…' : 'Test connection'}</button></div>
    </form> : <p className="inline-note">Provider credentials can only be changed or tested by an authenticated administrator.</p>}
    {!status.database_override_allowed && status.environment_configured && <p className="inline-note">The environment key remains authoritative. Set <code>FINNHUB_API_KEY_OVERRIDE_ENABLED=true</code> on the backend before an administrator can activate a database override.</p>}
    {save.isError && <ErrorState title="Finnhub configuration was not saved" error={save.error} compact />}
    {test.isError && <ErrorState title="Finnhub connection test failed" error={test.error} compact />}
    {test.data?.connected && <div className="inline-success"><StatusBadge status="CONNECTED" />Finnhub connection test passed using the {test.data.effective_source.toLowerCase()} credential.</div>}
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
