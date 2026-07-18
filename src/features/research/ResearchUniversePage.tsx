import {useQuery} from '@tanstack/react-query'

import {queries} from '../../api/queries'
import type {ResearchMVPCell} from '../../api/types'
import {DataTable, EmptyState, ErrorState, PageHeader, Skeleton, StatusBadge, TerminalMetric, TerminalPanel, formatNumber} from '../../components/ui'


const HEADERS: Record<string, string> = {
  FIXED_WEIGHT_REBALANCE: 'Fixed',
  SMA_CROSSOVER: 'SMA',
  RSI_MEAN_REVERSION: 'RSI',
  DONCHIAN_BREAKOUT: 'Donchian',
  VOLATILITY_TARGET_MOMENTUM: 'Vol-Target',
}

function MatrixCell({cell}: {cell?: ResearchMVPCell}) {
  if (!cell) return <span className="muted">Unavailable</span>
  return <div className="primary-cell research-mvp-cell">
    <StatusBadge status={cell.status} />
    <strong>{cell.score == null ? 'No score' : `Score ${formatNumber(cell.score)}`}</strong>
    <span>{cell.builder_ready ? 'Builder ready' : cell.approved ? 'Approved; SHADOW pending' : cell.blockers[0] || 'Queued'}</span>
  </div>
}

export function ResearchUniversePage() {
  const datasets = useQuery(queries.researchDatasetVersions())
  const universes = useQuery(queries.researchUniverses())
  const strategies = useQuery(queries.researchStrategies())
  const readiness = useQuery(queries.researchReadiness())
  const candidates = useQuery(queries.researchCandidateScores())
  const matrix = useQuery(queries.researchMVPMatrix())
  const error = datasets.error || universes.error || strategies.error || readiness.error || candidates.error || matrix.error
  if (datasets.isLoading || universes.isLoading || strategies.isLoading || matrix.isLoading) return <Skeleton lines={8} />
  if (error) return <ErrorState title="Research catalog is unavailable" error={error} onRetry={() => void Promise.all([
    datasets.refetch(), universes.refetch(), strategies.refetch(), readiness.refetch(), candidates.refetch(), matrix.refetch(),
  ])} />
  const active = datasets.data?.find((item) => item.status === 'ACTIVE')
  const universe = universes.data?.find((item) => item.active && item.key !== 'RECOMMENDATION_MVP')
  const approved = readiness.data?.filter((item) => item.approved).length || 0
  const builderReady = readiness.data?.filter((item) => item.builder_ready).length || 0
  const readyStocks = matrix.data?.stocks.filter((item) => item.eligible).length || 0
  return <div className="page-stack research-universe-page">
    <PageHeader eyebrow="Point-in-time research" title="Research Universe" description="The full 500-stock and 97-strategy catalog remains available while a controlled 5-stock × 5-strategy matrix is the only operational recommendation universe." />
    <div className="metric-grid">
      <TerminalMetric label="Dataset" value={active?.version || 'None active'} helper={active?.status || 'IMPORT REQUIRED'} />
      <TerminalMetric label="Catalog members" value={formatNumber(universe?.member_count || 0)} helper={universe?.membership_type || 'NO UNIVERSE'} />
      <TerminalMetric label="Pilot stocks ready" value={`${readyStocks} / 5`} helper="Finnhub + history + exact IBKR" />
      <TerminalMetric label="Approved / builder ready" value={`${approved} / ${builderReady}`} helper="Scoring + SHADOW gate" />
      <TerminalMetric label="Current candidates" value={formatNumber(candidates.data?.length || 0)} helper="Cached and unexpired" />
    </div>
    <TerminalPanel id="recommendation-mvp-matrix" title="Recommendation MVP readiness matrix" description="Each cell reports the exact stock-strategy pipeline state. Blocked stocks are never silently replaced.">
      <div className="table-scroll"><table className="data-table research-mvp-matrix">
        <thead><tr><th>Stock / Strategy</th>{matrix.data?.strategy_keys.map((key) => <th key={key}>{HEADERS[key] || key}</th>)}</tr></thead>
        <tbody>{matrix.data?.stocks.map((stock) => <tr key={stock.symbol}>
          <td><div className="primary-cell"><strong>{stock.symbol} · {stock.company}</strong><span>Finnhub {stock.finnhub_status}{stock.finnhub_symbol ? ` (${stock.finnhub_symbol})` : ''} · IBKR {stock.ibkr_status}{stock.conid ? ` conId ${stock.conid}` : ''}</span><span>{stock.valid_bar_count} valid bars · latest {stock.latest_date || 'none'} · {stock.provider || 'no provider'}</span>{stock.blockers.length ? <span>{stock.blockers.join(' · ')}</span> : null}</div></td>
          {matrix.data?.strategy_keys.map((key) => <td key={key}><MatrixCell cell={stock.strategies.find((item) => item.strategy_key === key)} /></td>)}
        </tr>)}</tbody>
      </table></div>
    </TerminalPanel>
    {active && <TerminalPanel id="research-manifest" title="Active bundle" description="Manifest, schema, count, and hash validation are recorded before atomic activation.">
      <div className="apply-summary"><StatusBadge status={active.status} /><div><strong>{active.bundle_name}</strong><span>Snapshot {active.snapshot_date} · SHA-256 {active.manifest_hash.slice(0, 16)}…</span></div></div>
      {active.validation_report.current_snapshot_only && <p className="inline-note">The 500-stock file is a current snapshot. It is not presented as historical point-in-time membership.</p>}
    </TerminalPanel>}
    <TerminalPanel id="research-strategies" title="Strategy catalog" description="Catalog hypotheses are not executable until exact semantic mapping, backtesting, scoring, approval, and SHADOW validation pass." defaultOpen={false}>
      {!strategies.data?.length ? <EmptyState title="No strategies imported" /> : <DataTable rows={strategies.data} getRowKey={(item) => item.id} columns={[
        {id: 'strategy', header: 'Strategy', cell: (item) => <div className="primary-cell"><strong>{item.name}</strong><span className="mono">{item.research_id}</span></div>},
        {id: 'family', header: 'Family / scope', cell: (item) => <span>{item.family} · {item.scope}</span>},
        {id: 'role', header: 'Role', cell: (item) => <StatusBadge status={item.role} />},
        {id: 'frequency', header: 'Frequencies', cell: (item) => item.supported_frequencies.join(', ')},
        {id: 'implementation', header: 'Implementation', cell: (item) => item.implementation_statuses.length ? item.implementation_statuses.join(', ') : 'DECLARED ONLY'},
      ]} />}
    </TerminalPanel>
  </div>
}
