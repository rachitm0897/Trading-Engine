import {useEffect, useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Check, Plus, Trash2} from 'lucide-react'
import {Link} from 'react-router-dom'

import {API_BASE_URL, mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {
  GoalTimeframe,
  PortfolioConstructionPlan,
  PortfolioConstructionRun,
  PortfolioGoalAllocation,
  RecommendationBatch,
  RecommendationBatchGoal,
} from '../../api/types'
import {
  ConfirmActionDialog,
  DataTable,
  EmptyState,
  ErrorState,
  PageHeader,
  Skeleton,
  StatusBadge,
  TerminalMetric,
  TerminalPanel,
  formatCompact,
  formatMoney,
  formatNumber,
  formatPercent,
  toNumber,
} from '../../components/ui'
import {useSelection} from '../../stores/useSelection'

const MAXIMUM_RISK: Record<GoalTimeframe, number> = {
  NOW: 1,
  HURRY: 2,
  FAST: 3,
  BUILD: 4,
  GROW: 5,
  COMPOUND: 5,
}

async function pollConstruction(initial: PortfolioConstructionRun, applying = false) {
  let value = initial
  const complete = (run: PortfolioConstructionRun) => applying
    ? !['QUEUED', 'APPLYING'].includes(run.application_status)
    : !['QUEUED', 'DISPATCHED', 'CALCULATING'].includes(run.status)
  for (let attempt = 0; attempt < 120 && !complete(value); attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 500))
    value = await request<PortfolioConstructionRun>(`portfolio-construction/runs/${value.id}/`)
  }
  if (applying && value.application_status !== 'APPLIED') {
    throw new Error(value.last_error || 'Portfolio construction apply did not complete')
  }
  if (!applying && value.status !== 'COMPLETED') {
    throw new Error(value.last_error || 'Portfolio construction preview did not complete')
  }
  return value
}

type GoalDraft = Pick<PortfolioGoalAllocation, 'id' | 'name' | 'timeframe_bucket' | 'risk_level' | 'enabled' | 'display_order'> & {allocation_percentage: number}

function asDraft(goal: PortfolioGoalAllocation): GoalDraft {
  return {...goal, allocation_percentage: toNumber(goal.allocation_percentage)}
}

export function PortfolioBuilderPage() {
  const queryClient = useQueryClient()
  const {portfolio, selectedPortfolioId} = useSelection()
  const plans = useQuery(queries.constructionPlans(selectedPortfolioId))
  const runs = useQuery(queries.constructionRuns(selectedPortfolioId))
  const system = useQuery(queries.system())
  const plan = plans.data?.[0]
  const [step, setStep] = useState(1)
  const [drafts, setDrafts] = useState<GoalDraft[]>([])
  const [batch, setBatch] = useState<RecommendationBatch | null>(null)
  const [preview, setPreview] = useState<PortfolioConstructionRun | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  useEffect(() => setDrafts((plan?.goals || []).map(asDraft)), [plan?.id, plan?.version])
  useEffect(() => {
    setStep(1)
    setBatch(null)
    setPreview(null)
  }, [selectedPortfolioId])

  const refreshPlan = async () => {
    await Promise.all([
      queryClient.invalidateQueries({queryKey: ['construction-plans', selectedPortfolioId ?? 'none']}),
      queryClient.invalidateQueries({queryKey: ['construction-runs', selectedPortfolioId ?? 'none']}),
    ])
  }
  const createPlan = useMutation({
    mutationFn: () => request<PortfolioConstructionPlan>('portfolio-construction/plans/', mutationOptions('POST', {
      portfolio_id: selectedPortfolioId,
      name: `${portfolio?.name || 'Portfolio'} goals`,
    })),
    onSuccess: refreshPlan,
  })
  const addGoal = useMutation({
    mutationFn: () => request<PortfolioGoalAllocation>(`portfolio-construction/plans/${plan?.id}/goals/`, mutationOptions('POST', {
      name: `Goal ${drafts.length + 1}`,
      allocation_percentage: '0',
      timeframe_bucket: 'BUILD',
      risk_level: 3,
      display_order: drafts.length,
    })),
    onSuccess: refreshPlan,
  })
  const removeGoal = useMutation({
    mutationFn: (goalId: number) => request<{id: number}>(`portfolio-construction/goals/${goalId}/`, mutationOptions('DELETE')),
    onSuccess: refreshPlan,
  })
  const generate = useMutation({
    mutationFn: async () => {
      if (!plan) throw new Error('Create a construction plan first')
      await Promise.all(drafts.map((goal) => request<PortfolioGoalAllocation>(
        `portfolio-construction/goals/${goal.id}/`,
        mutationOptions('PATCH', {
          name: goal.name,
          allocation_percentage: String(goal.allocation_percentage),
          timeframe_bucket: goal.timeframe_bucket,
          risk_level: goal.risk_level,
          enabled: goal.enabled,
          display_order: goal.display_order,
        }),
      )))
      return request<RecommendationBatch>(
        `portfolio-construction/plans/${plan.id}/recommendations/`,
        mutationOptions('POST', {}, true),
      )
    },
    onSuccess: async (result) => {
      setBatch(result)
      setPreview(null)
      setStep(2)
      await refreshPlan()
    },
  })
  const previewMutation = useMutation({
    mutationFn: async () => {
      const queued = await request<PortfolioConstructionRun>('portfolio-construction/preview/', mutationOptions('POST', {
        plan_id: plan?.id,
        refresh_history: true,
      }, true))
      return pollConstruction(queued)
    },
    onSuccess: async (run) => {
      setPreview(run)
      setStep(3)
      await refreshPlan()
    },
  })
  const applyMutation = useMutation({
    mutationFn: async () => {
      if (!preview) throw new Error('Preview the combined target before applying it')
      const queued = await request<PortfolioConstructionRun>(
        `portfolio-construction/runs/${preview.id}/apply/`,
        mutationOptions('POST', {plan_id: plan?.id, portfolio_id: selectedPortfolioId}, true),
      )
      return pollConstruction(queued, true)
    },
    onSuccess: async (run) => {
      setPreview(run)
      setConfirmOpen(false)
      await refreshPlan()
    },
  })

  const allocated = drafts.filter((goal) => goal.enabled).reduce((sum, goal) => sum + (Number.isFinite(goal.allocation_percentage) ? goal.allocation_percentage : 0), 0)
  const localErrors = [
    ...(drafts.filter((goal) => goal.enabled).length === 0 ? ['Add at least one enabled goal'] : []),
    ...(Math.abs(allocated - 100) > 0.000001 ? ['Enabled goals must total exactly 100%'] : []),
    ...drafts.filter((goal) => goal.enabled && goal.risk_level > MAXIMUM_RISK[goal.timeframe_bucket]).map((goal) => `${goal.name} exceeds the risk allowed for ${goal.timeframe_bucket}`),
  ]
  const shownPreview = preview || runs.data?.find((item) => item.status === 'COMPLETED') || null

  if (!selectedPortfolioId) return <EmptyState title="Select a portfolio" description="Portfolio Builder needs one broker-backed portfolio context." />
  if (plans.isLoading) return <Skeleton lines={7} />
  if (plans.isError) return <ErrorState title="Portfolio Builder is unavailable" error={plans.error} onRetry={() => void plans.refetch()} />

  return <div className="page-stack portfolio-builder">
    <PageHeader
      eyebrow="Full-universe recommendations"
      title="Portfolio Builder"
      description="Set your goals once. The recommendation system selects diversified stocks and one primary strategy per stock before the mandatory preview and SHADOW/PAPER apply gates."
    />
    {!plan ? <TerminalPanel id="create-construction-plan" title="Create a construction plan" description="One plan organizes up to ten virtual goals for this portfolio.">
      <button className="button-primary" disabled={createPlan.isPending} onClick={() => createPlan.mutate()}>{createPlan.isPending ? 'Creating…' : 'Start Portfolio Builder'}</button>
      {createPlan.isError && <ErrorState error={createPlan.error} compact />}
    </TerminalPanel> : <>
      <ol className="builder-steps" aria-label="Portfolio Builder steps">
        {['Goals', 'Recommendations', 'Preview & Apply'].map((label, index) => {
          const number = index + 1
          return <li key={label} className={step === number ? 'active' : step > number ? 'complete' : ''}>
            <button type="button" onClick={() => number < step && setStep(number)}><span>{step > number ? <Check /> : number}</span><strong>{label}</strong></button>
          </li>
        })}
      </ol>

      {step === 1 && <TerminalPanel id="portfolio-goals" title="1. Goals" description="Enabled goal allocations must total exactly 100%." collapsible={false}>
        <div className="builder-total"><strong>Allocated: {formatNumber(allocated)}% of 100%</strong><span className={localErrors.length ? 'field-error' : 'positive-text'}>{localErrors.length ? localErrors.join(' · ') : 'Ready to generate'}</span></div>
        <div className="goal-editor-list">
          {drafts.map((goal, index) => <GoalEditor key={goal.id} goal={goal} plan={plan} index={index}
            onChange={(changes) => setDrafts((current) => current.map((item) => item.id === goal.id ? {...item, ...changes} : item))}
            onRemove={() => removeGoal.mutate(goal.id)} removeDisabled={removeGoal.isPending} />)}
        </div>
        {!drafts.length && <EmptyState title="No goals yet" description="Add a goal row to begin." />}
        <div className="system-actions">
          <button className="button-secondary" disabled={addGoal.isPending || drafts.length >= 10} onClick={() => addGoal.mutate()}><Plus />Add goal</button>
          <button className="button-primary" disabled={Boolean(localErrors.length) || generate.isPending} onClick={() => generate.mutate()}>{generate.isPending ? 'Generating recommendations…' : 'Save goals & generate recommendations'}</button>
        </div>
        {(addGoal.isError || removeGoal.isError || generate.isError) && <ErrorState title="Recommendations could not be generated" error={addGoal.error || removeGoal.error || generate.error} compact />}
      </TerminalPanel>}

      {step === 2 && <RecommendationStep batch={batch} pending={generate.isPending || previewMutation.isPending}
        error={generate.error || previewMutation.error} onBack={() => setStep(1)} onRegenerate={() => generate.mutate()}
        onPreview={() => previewMutation.mutate()} />}

      {step === 3 && <PreviewApplyStep run={shownPreview} mode={system.data?.execution_mode || 'SHADOW'}
        pending={applyMutation.isPending} error={applyMutation.error} onBack={() => setStep(2)} onConfirm={() => setConfirmOpen(true)} />}

      <ConfirmActionDialog open={confirmOpen} title="Apply the combined portfolio target?"
        description={`This confirms one ${system.data?.execution_mode || 'SHADOW'} rebalance for the full portfolio. Generating recommendations created no orders, rebalances, or running strategies.`}
        confirmLabel="Apply one combined target" requireReason={false} danger={false} pending={applyMutation.isPending}
        onClose={() => setConfirmOpen(false)} onConfirm={async () => { await applyMutation.mutateAsync() }} />
    </>}
  </div>
}

function GoalEditor({goal, plan, onChange, onRemove, removeDisabled, index}: {
  goal: GoalDraft
  plan: PortfolioConstructionPlan
  onChange: (changes: Partial<GoalDraft>) => void
  onRemove: () => void
  removeDisabled: boolean
  index: number
}) {
  const riskOptions = plan.risk_options.filter((item) => item.level <= MAXIMUM_RISK[goal.timeframe_bucket])
  return <div className="goal-editor-row">
    <span className="goal-number">{index + 1}</span>
    <label>Goal name<input aria-label={`Goal ${index + 1} name`} value={goal.name} onChange={(event) => onChange({name: event.target.value})} /></label>
    <label>Allocation %<input aria-label={`${goal.name} allocation percentage`} type="number" min="0" max="100" step="0.01" value={goal.allocation_percentage} onChange={(event) => onChange({allocation_percentage: Number(event.target.value)})} /></label>
    <label>Timeframe<select aria-label={`${goal.name} timeframe`} value={goal.timeframe_bucket} onChange={(event) => {
      const timeframe = event.target.value as GoalTimeframe
      onChange({timeframe_bucket: timeframe, risk_level: Math.min(goal.risk_level, MAXIMUM_RISK[timeframe])})
    }}>{plan.timeframe_options.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>
    <label>Risk<select aria-label={`${goal.name} risk`} value={goal.risk_level} onChange={(event) => onChange({risk_level: Number(event.target.value)})}>{riskOptions.map((item) => <option key={item.level} value={item.level}>{item.label}</option>)}</select></label>
    <label className="goal-enabled"><input type="checkbox" checked={goal.enabled} onChange={(event) => onChange({enabled: event.target.checked})} />Enabled</label>
    <button className="icon-button" type="button" aria-label={`Remove ${goal.name}`} disabled={removeDisabled} onClick={onRemove}><Trash2 /></button>
  </div>
}

function RecommendationStep({batch, pending, error, onBack, onRegenerate, onPreview}: {
  batch: RecommendationBatch | null
  pending: boolean
  error: unknown
  onBack: () => void
  onRegenerate: () => void
  onPreview: () => void
}) {
  return <TerminalPanel id="plan-recommendations" title="2. Recommendations" description="Each goal receives a diversified stock set with one primary strategy per stock." collapsible={false}>
    {!batch ? <EmptyState title="No recommendation batch" description="Return to Goals and generate recommendations for the complete plan." /> : <>
      <div className="apply-summary"><StatusBadge status={batch.status} /><div><strong>Recommendations ready</strong><span>{batch.goals.length} goals · generated {new Date(batch.created_at).toLocaleString()}</span></div></div>
      {batch.goals.map((goal) => <RecommendationGoalCard key={goal.goal_id} goal={goal} />)}
      {batch.error && <ErrorState title="Recommendation batch failed" error={new Error(batch.error)} compact />}
    </>}
    {error ? <ErrorState title="Recommendation workflow failed" error={error} compact /> : null}
    <div className="system-actions">
      <button className="button-secondary" disabled={pending} onClick={onBack}>Back to goals</button>
      <button className="button-secondary" disabled={pending} onClick={onRegenerate}>{pending ? 'Working…' : 'Regenerate recommendations'}</button>
      <button className="button-primary" disabled={pending || batch?.status !== 'COMPLETED'} onClick={onPreview}>{pending ? 'Building preview…' : 'Preview portfolio'}</button>
    </div>
  </TerminalPanel>
}

function RecommendationGoalCard({goal}: {goal: RecommendationBatchGoal}) {
  return <section className="goal-selection-card">
    <header><div><h3>{goal.goal_name}</h3><p>{goal.timeframe} · Risk {goal.risk_level} · {goal.stocks.length} stocks · {formatPercent(goal.cash_weight)} cash</p></div><StatusBadge status={goal.status} /></header>
    {goal.stocks.length ? <div className="goal-stock-list">{goal.stocks.map((stock) => <article className="goal-stock-card" key={`${goal.goal_id}-${stock.instrument_id}`}>
      <header><div><strong>{stock.symbol} · {formatPercent(stock.weight)}</strong><span>{stock.company || stock.gics?.sector?.name || 'US equity'}</span></div><StatusBadge status={stock.execution_timeframe} /></header>
      <p><strong>{stock.strategy_name || stock.research_strategy_id}</strong> · primary strategy · {stock.execution_timeframe}</p>
      <p className="field-help">Expected return {formatPercent(stock.expected_return)} · volatility {formatPercent(stock.expected_volatility)} · drawdown {formatPercent(stock.expected_drawdown)}</p>
      <p className="field-help">{stock.reason}</p>
    </article>)}</div> : <p className="inline-note">This goal is intentionally 100% cash.</p>}
    {goal.fallback_tier === 5 && <p className="field-help">Using the latest validated snapshot during a provider outage. Freshness: {formatCompact(goal.freshness)}</p>}
  </section>
}

function PreviewApplyStep({run, mode, pending, error, onBack, onConfirm}: {
  run: PortfolioConstructionRun | null
  mode: string
  pending: boolean
  error: unknown
  onBack: () => void
  onConfirm: () => void
}) {
  if (!run) return <TerminalPanel id="construction-preview-empty" title="3. Preview & Apply" description="A completed preview is required before apply." collapsible={false}><EmptyState title="No preview yet" /><button className="button-secondary" onClick={onBack}>Back to recommendations</button></TerminalPanel>
  const targets = run.targets || []
  return <TerminalPanel id="construction-preview" title="3. Preview & Apply" description={`Review one combined target before it enters the existing ${mode} safety pipeline.`} collapsible={false}>
    <section className="metric-grid compact">
      <TerminalMetric label="Expected return" value={formatPercent(run.metrics.expected_return)} />
      <TerminalMetric label="Expected volatility" value={formatPercent(run.metrics.expected_volatility)} />
      <TerminalMetric label="Sharpe ratio" value={formatNumber(run.metrics.sharpe_ratio)} />
      <TerminalMetric label="Combined cash" value={formatPercent(run.final_target_weights.cash)} />
      <TerminalMetric label="Net turnover" value={formatPercent(run.rebalance?.planned_turnover)} />
      <TerminalMetric label="Mode" value={<StatusBadge status={run.rebalance?.mode || mode} />} />
    </section>
    <DataTable rows={targets} columns={[
      {id: 'stock', header: 'Stock', cell: (item) => <div className="primary-cell"><strong className="mono">{item.symbol}</strong>{item.shared_across_goals && <span>Shared by {item.goal_contributions.length} goals</span>}</div>},
      {id: 'current', header: 'Current', align: 'right' as const, cell: (item) => formatPercent(item.current_weight)},
      {id: 'target', header: 'Proposed', align: 'right' as const, cell: (item) => formatPercent(item.target_weight)},
      {id: 'value', header: 'Target value', align: 'right' as const, cell: (item) => formatMoney(item.target_value)},
      {id: 'goals', header: 'Goal contributions', cell: (item) => item.goal_contributions.map((value) => `${value.goal_name} ${formatPercent(value.portfolio_contribution)}`).join(' · ')},
    ]} getRowKey={(item) => item.id} emptyTitle="Cash-only combined target" />
    <DataTable rows={run.planned_trades || []} columns={[
      {id: 'stock', header: 'Stock', cell: (item) => <strong className="mono">{item.symbol}</strong>},
      {id: 'weights', header: 'Current → target', cell: (item) => `${formatPercent(item.current_weight)} → ${formatPercent(item.target_weight)}`},
      {id: 'side', header: 'Side', cell: (item) => <StatusBadge status={item.side} />},
      {id: 'quantity', header: 'Quantity', align: 'right' as const, cell: (item) => formatNumber(item.quantity)},
      {id: 'state', header: 'State', cell: (item) => <StatusBadge status={item.suppressed ? item.suppression_reason || 'SUPPRESSED' : 'PLANNED'} />},
    ]} getRowKey={(item) => item.instrument_id} emptyTitle="No net trades required" />
    {run.applied_rebalance ? <div className="inline-success"><StatusBadge status={run.applied_rebalance.status} /><div><strong>Applied through rebalance {run.applied_rebalance.id}</strong><p>The recommendation batch itself created no orders. Execution remains governed by {mode} controls.</p><div className="inline-links"><a href={`${API_BASE_URL}/portfolio-construction/runs/${run.id}/`} target="_blank" rel="noreferrer">Construction run {run.id}</a><Link to="/portfolio">View portfolio</Link><Link to="/activity">Orders & activity</Link></div></div></div> : <div className="system-actions"><button className="button-secondary" onClick={onBack}>Back to recommendations</button><button className="button-primary" disabled={pending} onClick={onConfirm}>{pending ? 'Applying…' : `Confirm ${mode} apply`}</button></div>}
    {error ? <ErrorState title="Construction application was blocked" error={error} compact /> : null}
  </TerminalPanel>
}
