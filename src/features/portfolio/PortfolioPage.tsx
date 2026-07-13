import {useMemo, useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Banknote, Layers3, PieChart, Scale, WalletCards} from 'lucide-react'
import {mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {AllocationPolicy, Position, PositionSizingDecision, RebalanceRun, RebalanceTarget} from '../../api/types'
import {TimeSeriesChart} from '../../components/charts/TimeSeriesChart'
import {CollapsibleSection, DataTable, ErrorState, Freshness, MetricCard, PageHeader, Panel, Skeleton, StatusBadge, formatMoney, formatNumber, formatPercent, toNumber} from '../../components/ui'
import {useSelection} from '../../stores/useSelection'

export function PortfolioPage() {
  const queryClient = useQueryClient()
  const {portfolio, account, selectedPortfolioId} = useSelection()
  const positions = useQuery(queries.positions(selectedPortfolioId))
  const series = useQuery(queries.portfolioSeries(selectedPortfolioId))
  const allocationPolicies = useQuery(queries.allocationPolicies())
  const allocationRuns = useQuery(queries.allocationRuns())
  const rebalancePolicies = useQuery(queries.rebalancePolicies())
  const rebalanceRuns = useQuery(queries.rebalanceRuns())
  const instruments = useQuery(queries.instruments())
  const [preview, setPreview] = useState<RebalanceRun | null>(null)
  const [sizing, setSizing] = useState<PositionSizingDecision | null>(null)

  const portfolioPositions = useMemo(() => (positions.data || []).filter((item) => !selectedPortfolioId || item.portfolio_id === selectedPortfolioId), [positions.data, selectedPortfolioId])
  const gross = portfolioPositions.reduce((sum, item) => sum + Math.abs(toNumber(item.market_value)), 0)
  const net = portfolioPositions.reduce((sum, item) => sum + toNumber(item.market_value), 0)
  const concentration = gross ? Math.max(0, ...portfolioPositions.map((item) => Math.abs(toNumber(item.market_value)) / gross)) : 0
  const policyRows = (allocationPolicies.data || []).filter((item) => !selectedPortfolioId || item.portfolio_id === selectedPortfolioId)
  const rebalancePolicyRows = (rebalancePolicies.data || []).filter((item) => !selectedPortfolioId || item.portfolio_id === selectedPortfolioId)

  const flow = useMutation({
    mutationFn: (payload: {flow_type: string; amount: string; liquidation_policy: string}) => request<{id: number; status: string}>('allocations/flows/', mutationOptions('POST', {portfolio_id: selectedPortfolioId, ...payload}, true)),
    onSuccess: async () => { await queryClient.invalidateQueries({queryKey: ['allocation-runs']}) },
  })
  const rebalance = useMutation({
    mutationFn: () => request<RebalanceRun>('rebalancing/preview/', mutationOptions('POST', {portfolio_id: selectedPortfolioId, trigger: 'MANUAL'}, true)),
    onSuccess: async (data) => {setPreview(data); await queryClient.invalidateQueries({queryKey: ['rebalance-runs']})},
  })
  const size = useMutation({
    mutationFn: (payload: Record<string, string | number | null>) => request<PositionSizingDecision>('position-sizing/preview/', mutationOptions('POST', {portfolio_id: selectedPortfolioId, ...payload}, true)),
    onSuccess: setSizing,
  })

  const holdingColumns = [
    {id: 'instrument', header: 'Holding', cell: (item: Position) => <div className="primary-cell"><strong className="mono">{item.symbol}</strong><span>{item.asset_class} · {item.currency}</span></div>},
    {id: 'quantity', header: 'Quantity', align: 'right' as const, className: 'mono', cell: (item: Position) => formatNumber(item.quantity)},
    {id: 'average', header: 'Average cost', align: 'right' as const, className: 'mono', cell: (item: Position) => formatMoney(item.average_cost, item.currency)},
    {id: 'price', header: 'Market price', align: 'right' as const, className: 'mono', cell: (item: Position) => formatMoney(item.market_price, item.currency)},
    {id: 'value', header: 'Market value', align: 'right' as const, className: 'mono', cell: (item: Position) => formatMoney(item.market_value, item.currency)},
    {id: 'weight', header: 'Gross weight', align: 'right' as const, cell: (item: Position) => formatPercent(gross ? Math.abs(toNumber(item.market_value)) / gross : 0)},
  ]
  const driftColumns = [
    {id: 'instrument', header: 'Instrument', cell: (item: RebalanceTarget) => <code>{instruments.data?.find((value) => value.id === item.instrument_id)?.symbol || item.instrument_id}</code>},
    {id: 'current', header: 'Current', align: 'right' as const, cell: (item: RebalanceTarget) => formatPercent(item.current_weight)},
    {id: 'target', header: 'Target', align: 'right' as const, cell: (item: RebalanceTarget) => formatPercent(item.target_weight)},
    {id: 'drift', header: 'Drift', align: 'right' as const, cell: (item: RebalanceTarget) => formatPercent(item.drift)},
    {id: 'trade', header: 'Preview quantity', align: 'right' as const, className: 'mono', cell: (item: RebalanceTarget) => formatNumber(item.trade_quantity)},
    {id: 'state', header: 'State', cell: (item: RebalanceTarget) => <StatusBadge status={item.suppressed ? item.suppression_reason || 'SUPPRESSED' : 'PLANNED'} />},
  ]

  return <div className="page-stack">
    <PageHeader eyebrow="Capital & allocation" title={portfolio?.name || 'Portfolio'} description="Holdings, cash, exposure, allocation, and drift for the selected broker-backed portfolio." actions={<Freshness updatedAt={Math.max(positions.dataUpdatedAt, series.dataUpdatedAt)} stale={positions.isStale || series.isStale} fetching={positions.isFetching || series.isFetching} onRefresh={() => {void positions.refetch(); void series.refetch()}} />} />
    <section className="metric-grid compact">
      <MetricCard label="NAV" value={formatMoney(account?.net_liquidation, account?.base_currency)} icon={<WalletCards />} />
      <MetricCard label="Cash" value={formatMoney(account?.available_cash, account?.base_currency)} icon={<Banknote />} helper={portfolio ? `${formatPercent(portfolio.cash_buffer_pct)} buffer policy` : undefined} />
      <MetricCard label="Gross exposure" value={formatMoney(gross, account?.base_currency)} icon={<Layers3 />} />
      <MetricCard label="Net exposure" value={formatMoney(net, account?.base_currency)} icon={<Scale />} />
      <MetricCard label="Largest concentration" value={formatPercent(concentration)} icon={<PieChart />} />
    </section>
    <div className="portfolio-grid">
      <Panel title="NAV & P&L history" description={`Source: ${series.data?.source || 'loading persisted observations'}`} className="portfolio-history">{series.isLoading ? <Skeleton height={280} /> : series.isError ? <ErrorState error={series.error} onRetry={() => void series.refetch()} compact /> : <TimeSeriesChart height={280} lines={[{name: 'NAV', data: series.data?.nav || [], color: '#4676f2', type: 'area'}, {name: 'P&L', data: series.data?.pnl || [], color: '#0d9488'}]} />}</Panel>
      <Panel title="Allocation by instrument" description="Current marked market value as a share of gross exposure"><AllocationBars rows={(series.data?.allocation_by_instrument || []).map((item) => ({id: item.instrument_id, name: item.symbol, weight: item.weight, value: item.value}))} currency={account?.base_currency} /></Panel>
      <Panel title="Allocation by strategy" description="Configured capital shares; actual attribution remains ledger-backed"><AllocationBars rows={policyRows.map((item) => ({id: item.id, name: item.strategy, weight: toNumber(item.target_share), value: null}))} currency={account?.base_currency} /></Panel>
    </div>
    <Panel title="Holdings" description={`${portfolioPositions.length} marked positions`}>{positions.isLoading ? <Skeleton lines={5} /> : positions.isError ? <ErrorState error={positions.error} onRetry={() => void positions.refetch()} /> : <DataTable rows={portfolioPositions} columns={holdingColumns} getRowKey={(item) => item.id} emptyTitle="No holdings" emptyDescription="Broker-synchronized positions for the selected portfolio will appear here." />}</Panel>
    <Panel title="Drift" description="Create a SHADOW preview to compare current and net strategy targets" actions={<button className="button-secondary" disabled={!selectedPortfolioId || rebalance.isPending} onClick={() => rebalance.mutate()}>{rebalance.isPending ? 'Calculating…' : 'Preview rebalance'}</button>}>{rebalance.isError && <ErrorState title="Rebalance preview was blocked" error={rebalance.error} compact />}<DataTable rows={preview?.targets || []} columns={driftColumns} getRowKey={(item) => item.id} emptyTitle="No drift preview" emptyDescription="A preview creates planning records only and never creates an order." /></Panel>
    <section className="advanced-stack" aria-label="Advanced portfolio tools">
      <CollapsibleSection title="Portfolio flow allocation" description="Deposit and withdrawal allocation, kept out of the everyday holdings view."><FlowForm pending={flow.isPending} error={flow.error} result={flow.data} onSubmit={(payload) => flow.mutate(payload)} /><DataTable rows={(allocationRuns.data || []).filter((item) => !selectedPortfolioId || item.portfolio_id === selectedPortfolioId).slice(0, 10)} columns={allocationRunColumns} getRowKey={(item) => item.id} emptyTitle="No allocation runs" /></CollapsibleSection>
      <CollapsibleSection title="Position sizing details" description="Operator preview of the constraints applied before risk and OMS."><SizingForm instruments={instruments.data || []} pending={size.isPending} error={size.error} result={sizing} onSubmit={(payload) => size.mutate(payload)} /></CollapsibleSection>
      <CollapsibleSection title="Policy internals" description="Allocation and rebalance policy values used by the planning services."><PolicyTables allocation={policyRows} rebalance={rebalancePolicyRows} runs={(rebalanceRuns.data || []).filter((item) => !selectedPortfolioId || item.portfolio_id === selectedPortfolioId)} /></CollapsibleSection>
    </section>
  </div>
}

function AllocationBars({rows, currency}: {rows: {id: number; name: string; weight: number; value: number | null}[]; currency?: string}) {
  if (!rows.length) return <div className="empty-inline">No allocation data for this portfolio.</div>
  const maximum = Math.max(...rows.map((item) => Math.abs(item.weight)), 0.01)
  return <ul className="allocation-bars">{rows.map((item) => <li key={item.id}><div><strong>{item.name}</strong><span>{formatPercent(item.weight)}{item.value !== null ? ` · ${formatMoney(item.value, currency)}` : ''}</span></div><div><i style={{width: `${Math.abs(item.weight) / maximum * 100}%`}} /></div></li>)}</ul>
}

function FlowForm({pending, error, result, onSubmit}: {pending: boolean; error: unknown; result?: {id: number; status: string}; onSubmit: (payload: {flow_type: string; amount: string; liquidation_policy: string}) => void}) {
  const submit = (event: React.FormEvent<HTMLFormElement>) => {event.preventDefault(); const form = new FormData(event.currentTarget); onSubmit({flow_type: String(form.get('flow_type')), amount: String(form.get('amount')), liquidation_policy: String(form.get('liquidation_policy'))})}
  return <><form className="form-grid three-columns" onSubmit={submit}><label>Flow type<select name="flow_type"><option>DEPOSIT</option><option>WITHDRAWAL</option><option>INTERNAL_TRANSFER_IN</option><option>INTERNAL_TRANSFER_OUT</option></select></label><label>Amount<input name="amount" type="number" min="0.01" step="0.01" required /></label><label>Liquidation policy<select name="liquidation_policy"><option>PROPORTIONAL</option><option>LOWEST_CONVICTION_FIRST</option><option>MOST_LIQUID_FIRST</option><option>LOWEST_COST_FIRST</option><option>PRIORITY_ORDER</option></select></label><button className="button-primary form-submit" disabled={pending}>{pending ? 'Calculating…' : 'Calculate flow'}</button></form>{error && <ErrorState title="Flow was blocked" error={error} compact />}{result && <div className="inline-success"><StatusBadge status={result.status} />Allocation run {result.id} recorded.</div>}</>
}

function SizingForm({instruments, pending, error, result, onSubmit}: {instruments: {id: number; symbol: string}[]; pending: boolean; error: unknown; result: PositionSizingDecision | null; onSubmit: (payload: Record<string, string | number | null>) => void}) {
  const submit = (event: React.FormEvent<HTMLFormElement>) => {event.preventDefault(); const form = new FormData(event.currentTarget); onSubmit({instrument_id: Number(form.get('instrument_id')), side: String(form.get('side')), target_quantity: String(form.get('target_quantity')), entry_price: String(form.get('entry_price')), stop_price: form.get('stop_price') ? String(form.get('stop_price')) : null, adv: String(form.get('adv'))})}
  return <><form className="form-grid four-columns" onSubmit={submit}><label>Instrument<select name="instrument_id" required><option value="">Choose</option>{instruments.map((item) => <option key={item.id} value={item.id}>{item.symbol}</option>)}</select></label><label>Side<select name="side"><option>BUY</option><option>SELL</option></select></label><label>Target quantity<input name="target_quantity" type="number" min="0" step="any" required /></label><label>Entry price<input name="entry_price" type="number" min="0.0001" step="any" required /></label><label>Stop price<input name="stop_price" type="number" min="0" step="any" /></label><label>Average daily volume<input name="adv" type="number" min="0" step="any" required /></label><button className="button-primary form-submit" disabled={pending}>{pending ? 'Sizing…' : 'Preview sizing'}</button></form>{error && <ErrorState title="Sizing preview was blocked" error={error} compact />}{result && <div className="sizing-result"><div><span>Target</span><strong>{formatNumber(result.target_quantity)}</strong></div><div><span>Approved</span><strong>{formatNumber(result.approved_quantity)}</strong></div><div><span>Binding constraint</span><strong>{result.binding_constraint || 'None'}</strong></div><div><span>Decision</span><StatusBadge status={result.rejected_reason ? 'REJECTED' : 'PREVIEW'} /></div></div>}</>
}

const allocationRunColumns = [
  {id: 'type', header: 'Type', cell: (item: import('../../api/types').AllocationRun) => item.flow_type},
  {id: 'amount', header: 'Amount', align: 'right' as const, cell: (item: import('../../api/types').AllocationRun) => formatNumber(item.amount)},
  {id: 'approved', header: 'Approved', align: 'right' as const, cell: (item: import('../../api/types').AllocationRun) => formatNumber(item.approved_amount)},
  {id: 'policy', header: 'Policy', cell: (item: import('../../api/types').AllocationRun) => item.liquidation_policy},
  {id: 'status', header: 'Status', cell: (item: import('../../api/types').AllocationRun) => <StatusBadge status={item.status} />},
]

function PolicyTables({allocation, rebalance, runs}: {allocation: AllocationPolicy[]; rebalance: import('../../api/types').RebalancePolicy[]; runs: RebalanceRun[]}) {
  return <div className="page-stack"><h3>Strategy capital policy</h3><DataTable rows={allocation} columns={[{id: 'strategy', header: 'Strategy', cell: (item) => item.strategy}, {id: 'share', header: 'Target share', cell: (item) => formatPercent(item.target_share)}, {id: 'bounds', header: 'Min / max', cell: (item) => `${formatPercent(item.minimum_share)} / ${formatPercent(item.maximum_share)}`}, {id: 'priority', header: 'Priority', cell: (item) => item.priority}, {id: 'state', header: 'State', cell: (item) => <StatusBadge status={item.enabled ? 'ENABLED' : 'DISABLED'} />}]} getRowKey={(item) => item.id} /><h3>Rebalance policy</h3><DataTable rows={rebalance} columns={[{id: 'mode', header: 'Mode', cell: (item) => <StatusBadge status={item.mode} />}, {id: 'instrument', header: 'Instrument drift', cell: (item) => formatPercent(item.instrument_drift_threshold)}, {id: 'portfolio', header: 'Portfolio drift', cell: (item) => formatPercent(item.portfolio_drift_threshold)}, {id: 'turnover', header: 'Max turnover', cell: (item) => formatPercent(item.maximum_turnover)}, {id: 'sequence', header: 'Sequence', cell: (item) => item.sell_before_buy ? 'Sells before buys' : 'Net sequence'}]} getRowKey={(item) => item.id} /><h3>Recent rebalance runs</h3><DataTable rows={runs.slice(0, 10)} columns={[{id: 'trigger', header: 'Trigger', cell: (item) => item.trigger}, {id: 'mode', header: 'Mode', cell: (item) => <StatusBadge status={item.mode} />}, {id: 'phase', header: 'Phase', cell: (item) => item.phase}, {id: 'drift', header: 'Total drift', cell: (item) => formatPercent(item.total_drift)}, {id: 'status', header: 'Status', cell: (item) => <StatusBadge status={item.status} />}]} getRowKey={(item) => item.id} /></div>
}
