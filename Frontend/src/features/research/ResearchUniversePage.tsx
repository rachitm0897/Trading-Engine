import {useQuery} from '@tanstack/react-query'

import {queries} from '../../api/queries'
import {DataTable, EmptyState, ErrorState, PageHeader, Skeleton, StatusBadge, TerminalMetric, TerminalPanel, formatNumber} from '../../components/ui'


export function ResearchUniversePage() {
  const datasets = useQuery(queries.researchDatasetVersions())
  const universes = useQuery(queries.researchUniverses())
  const strategies = useQuery(queries.researchStrategies())
  const readiness = useQuery(queries.researchReadiness())
  const candidates = useQuery(queries.researchCandidateScores())
  const error = datasets.error || universes.error || strategies.error || readiness.error || candidates.error
  if (datasets.isLoading || universes.isLoading || strategies.isLoading) return <Skeleton lines={8} />
  if (error) return <ErrorState title="Research catalog is unavailable" error={error} onRetry={() => void Promise.all([
    datasets.refetch(), universes.refetch(), strategies.refetch(), readiness.refetch(), candidates.refetch(),
  ])} />
  const active = datasets.data?.find((item) => item.status === 'ACTIVE')
  const universe = universes.data?.find((item) => item.active)
  const approved = readiness.data?.filter((item) => item.approved).length || 0
  const builderReady = readiness.data?.filter((item) => item.builder_ready).length || 0
  return <div className="page-stack research-universe-page">
    <PageHeader
      eyebrow="Point-in-time research"
      title="Research Universe"
      description="Versioned stock and strategy metadata, data readiness, experimental approval, and recommendation inputs. Catalog entries are not executable code."
    />
    <div className="metric-grid">
      <TerminalMetric label="Dataset" value={active?.version || 'None active'} helper={active?.status || 'IMPORT REQUIRED'} />
      <TerminalMetric label="Universe members" value={formatNumber(universe?.member_count || 0)} helper={universe?.membership_type || 'NO UNIVERSE'} />
      <TerminalMetric label="Strategy hypotheses" value={formatNumber(strategies.data?.length || 0)} helper="Catalog only by default" />
      <TerminalMetric label="Approved / builder ready" value={`${approved} / ${builderReady}`} helper="Exact implementation + SHADOW gate" />
      <TerminalMetric label="Current candidates" value={formatNumber(candidates.data?.length || 0)} helper="Cached and unexpired" />
    </div>
    {active && <TerminalPanel id="research-manifest" title="Active bundle" description="Manifest, schema, count, and hash validation are recorded before atomic activation.">
      <div className="apply-summary"><StatusBadge status={active.status} /><div><strong>{active.bundle_name}</strong><span>Snapshot {active.snapshot_date} · SHA-256 {active.manifest_hash.slice(0, 16)}…</span></div></div>
      {active.validation_report.current_snapshot_only && <p className="inline-note">The 500-stock file is a current snapshot. It is not shown as historical point-in-time membership and cannot support an unbiased historical-performance claim.</p>}
    </TerminalPanel>}
    <TerminalPanel id="research-strategies" title="Strategy catalog" description="All hypotheses remain research-only until exact semantics, validation, approval, and SHADOW evaluation pass.">
      {!strategies.data?.length ? <EmptyState title="No strategies imported" /> : <DataTable
        rows={strategies.data}
        getRowKey={(item) => item.id}
        columns={[
          {id: 'strategy', header: 'Strategy', cell: (item) => <div className="primary-cell"><strong>{item.name}</strong><span className="mono">{item.research_id}</span></div>},
          {id: 'family', header: 'Family / scope', cell: (item) => <span>{item.family} · {item.scope}</span>},
          {id: 'role', header: 'Role', cell: (item) => <StatusBadge status={item.role} />},
          {id: 'frequency', header: 'Frequencies', cell: (item) => item.supported_frequencies.join(', ')},
          {id: 'implementation', header: 'Implementation', cell: (item) => item.implementation_statuses.length ? item.implementation_statuses.join(', ') : 'DECLARED ONLY'},
        ]}
      />}
    </TerminalPanel>
  </div>
}
