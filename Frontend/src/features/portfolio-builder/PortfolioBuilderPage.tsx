import {useEffect, useMemo, useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Check, Plus, Trash2} from 'lucide-react'
import {Link} from 'react-router-dom'

import {API_BASE_URL, mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {
  ConstructionStrategyOption,
  GoalInstrumentSelection,
  GoalRecommendationRun,
  GoalStrategyAssignment,
  GoalTimeframe,
  Instrument,
  InstrumentResolution,
  PortfolioConstructionPlan,
  PortfolioConstructionRun,
  PortfolioGoalAllocation,
  Scalar,
  StrategyPolicies,
} from '../../api/types'
import {BrokerInstrumentSearch} from '../../components/BrokerInstrumentSearch'
import {SchemaParameterForm} from '../../components/SchemaParameterForm'
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
import {goalAllowsManualEdits, recommendationBlockerText, recommendationCanBeAccepted} from '../research/recommendationState'


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
  if (applying) {
    if (value.application_status === 'FAILED') {
      throw new Error(value.last_error || 'Portfolio construction could not be applied')
    }
    if (value.application_status !== 'APPLIED') {
      throw new Error('Portfolio construction apply did not complete before polling timed out')
    }
  } else {
    if (value.status === 'FAILED') {
      throw new Error(value.last_error || 'Portfolio construction preview failed')
    }
    if (value.status !== 'COMPLETED') {
      throw new Error('Portfolio construction preview did not complete before polling timed out')
    }
  }
  return value
}

async function pollRecommendation(initial: GoalRecommendationRun) {
  let value = initial
  for (let attempt = 0; attempt < 120 && ['QUEUED', 'RUNNING'].includes(value.status); attempt += 1) {
    await new Promise((resolve) => window.setTimeout(resolve, 500))
    value = await request<GoalRecommendationRun>(`portfolio-construction/recommendations/${value.id}/`)
  }
  if (value.status === 'FAILED') throw new Error(value.error || 'Recommendation generation failed')
  if (!['COMPLETED', 'BLOCKED'].includes(value.status)) throw new Error('Recommendation did not complete before polling timed out')
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
  const instruments = useQuery(queries.instruments())
  const system = useQuery(queries.system())
  const plan = plans.data?.[0]
  const [step, setStep] = useState(1)
  const [drafts, setDrafts] = useState<GoalDraft[]>([])
  const [preview, setPreview] = useState<PortfolioConstructionRun | null>(null)
  const [confirmOpen, setConfirmOpen] = useState(false)

  useEffect(() => {
    setDrafts((plan?.goals || []).map(asDraft))
  }, [plan?.id, plan?.version])
  useEffect(() => {
    setStep(1)
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
  const saveGoals = useMutation({
    mutationFn: async () => {
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
    },
    onSuccess: refreshPlan,
  })
  const removeGoal = useMutation({
    mutationFn: (goalId: number) => request<{id: number}>(`portfolio-construction/goals/${goalId}/`, mutationOptions('DELETE')),
    onSuccess: refreshPlan,
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
  const validDraft = localErrors.length === 0
  const stockInstruments = (instruments.data || []).filter((item) => item.asset_class === 'STK' && item.active && item.tradable)
  const shownPreview = preview || runs.data?.find((item) => item.status === 'COMPLETED') || null
  const previewErrorMessage = previewMutation.error instanceof Error ? previewMutation.error.message : ''

  if (!selectedPortfolioId) return <EmptyState title="Select a portfolio" description="Portfolio Builder needs one broker-backed portfolio context." />
  if (plans.isLoading) return <Skeleton lines={7} />
  if (plans.isError) return <ErrorState title="Portfolio Builder is unavailable" error={plans.error} onRetry={() => void plans.refetch()} />

  return <div className="page-stack portfolio-builder">
    <PageHeader
      eyebrow="Deterministic construction"
      title="Portfolio Builder"
      description="Divide one portfolio into goal slices, construct each slice independently, and apply one combined paper-only rebalance."
    />
    {!plan ? <TerminalPanel id="create-construction-plan" title="Create a construction plan" description="One plan organizes up to ten virtual goals for this portfolio.">
      <button className="button-primary" disabled={createPlan.isPending} onClick={() => createPlan.mutate()}>{createPlan.isPending ? 'Creating…' : 'Start Portfolio Builder'}</button>
      {createPlan.isError && <ErrorState error={createPlan.error} compact />}
    </TerminalPanel> : <>
      <ol className="builder-steps" aria-label="Portfolio Builder steps">
        {['Allocate goals', 'Add stocks & assign strategies', 'Preview', 'Apply'].map((label, index) => {
          const number = index + 1
          return <li key={label} className={step === number ? 'active' : step > number ? 'complete' : ''}>
            <button type="button" onClick={() => number <= step && setStep(number)}><span>{step > number ? <Check /> : number}</span><strong>{label}</strong></button>
          </li>
        })}
      </ol>
      {step === 1 && <TerminalPanel id="allocate-goals" title="1. Allocate goals" description="Draft percentages may be incomplete while editing; continuing requires exactly 100%." collapsible={false}>
        <div className="builder-total"><strong>Allocated: {formatNumber(allocated)}% of 100%</strong><span className={validDraft ? 'positive-text' : 'field-error'}>{validDraft ? 'Ready to continue' : localErrors.join(' · ')}</span></div>
        <div className="goal-editor-list">
          {drafts.map((goal, index) => <GoalEditor
            key={goal.id}
            goal={goal}
            plan={plan}
            onChange={(changes) => setDrafts((current) => current.map((item) => item.id === goal.id ? {...item, ...changes} : item))}
            onRemove={() => removeGoal.mutate(goal.id)}
            removeDisabled={removeGoal.isPending}
            index={index}
          />)}
        </div>
        {!drafts.length && <EmptyState title="No goals yet" description="Add a goal row to begin allocating this portfolio." />}
        <div className="system-actions">
          <button className="button-secondary" disabled={addGoal.isPending || drafts.length >= 10} onClick={() => addGoal.mutate()}><Plus />Add goal</button>
          <button className="button-primary" disabled={!validDraft || saveGoals.isPending} onClick={() => saveGoals.mutate(undefined, {onSuccess: () => setStep(2)})}>{saveGoals.isPending ? 'Saving…' : 'Save & select investments'}</button>
        </div>
        {(addGoal.isError || saveGoals.isError || removeGoal.isError) && <ErrorState title="Goal changes were not saved" error={addGoal.error || saveGoals.error || removeGoal.error} compact />}
      </TerminalPanel>}
      {step === 2 && <TerminalPanel id="stock-strategy-assignments" title="2. Add stocks and assign strategies" description="Stocks define each optimizer universe. Strategy assignments divide ownership of a stock weight without changing it." collapsible={false}>
        <div className="goal-selection-list">
          {plan.goals.filter((goal) => goal.enabled).map((goal) => <GoalSelections key={goal.id} goal={goal} instruments={stockInstruments} />)}
        </div>
        <div className="system-actions">
          <button className="button-secondary" onClick={() => setStep(1)}>Back to allocations</button>
          <button className="button-primary" disabled={!plan.ready_to_preview || previewMutation.isPending} onClick={() => previewMutation.mutate()}>{previewMutation.isPending ? 'Constructing goals…' : 'Preview combined portfolio'}</button>
        </div>
        {previewMutation.isError && <>
          <ErrorState title="Construction preview failed" error={previewMutation.error} compact />
          {previewErrorMessage.includes('Finnhub API key is not configured') && <p className="inline-note">Portfolio preview needs recent price history. <Link to="/system">Configure Finnhub in System</Link>, then retry.</p>}
        </>}
      </TerminalPanel>}
      {step === 3 && <PreviewStep run={shownPreview} onBack={() => setStep(2)} onContinue={() => setStep(4)} />}
      {step === 4 && <TerminalPanel id="apply-construction" title="4. Apply once" description={`Apply one combined target through the existing ${system.data?.execution_mode || 'SHADOW'} rebalance and execution safety pipeline.`} collapsible={false}>
        {!shownPreview ? <EmptyState title="No completed preview" description="Return to step 2 and preview the construction first." /> : <>
          <div className="apply-summary">
            <StatusBadge status={shownPreview.application_status} />
            <div><strong>Construction run {shownPreview.id}</strong><span>{shownPreview.targets?.length || 0} merged stock targets · {shownPreview.goals?.length || 0} goals</span></div>
          </div>
          {shownPreview.applied_rebalance ? <div className="inline-success"><StatusBadge status={shownPreview.applied_rebalance.status} /><div><strong>Applied through rebalance {shownPreview.applied_rebalance.id}</strong><p>Strategy instances were left disabled in SHADOW mode for manual review.</p><div className="inline-links"><a href={`${API_BASE_URL}/portfolio-construction/runs/${shownPreview.id}/`} target="_blank" rel="noreferrer">Construction run {shownPreview.id}</a><a href={`${API_BASE_URL}/rebalancing/runs/${shownPreview.applied_rebalance.id}/`} target="_blank" rel="noreferrer">Rebalance {shownPreview.applied_rebalance.id}</a>{shownPreview.metrics.strategy_instances?.map((item) => <Link key={item.strategy_instance_id} to={`/strategies/${item.strategy_instance_id}`}>Strategy {item.strategy_instance_id}</Link>)}<Link to="/portfolio">View portfolio</Link><Link to="/strategies">Review strategies</Link><Link to="/activity">Orders & activity</Link></div></div></div> : <div className="system-actions"><button className="button-secondary" onClick={() => setStep(3)}>Back to preview</button><button className="button-primary" disabled={Boolean(shownPreview.goals?.some((goal) => goal.apply_blocked)) || applyMutation.isPending} onClick={() => setConfirmOpen(true)}>Apply combined target</button></div>}
          {shownPreview.goals?.some((goal) => goal.apply_blocked) && <div className="inline-warning"><StatusBadge status="BLOCKED" /><p>Add at least one stock to every non-NOW goal and make each stock's enabled strategy shares total 100% before applying.</p></div>}
          {applyMutation.isError && <ErrorState title="Construction application was blocked" error={applyMutation.error} compact />}
        </>}
      </TerminalPanel>}
      <ConfirmActionDialog
        open={confirmOpen}
        title="Apply the combined portfolio target?"
        description="This confirms one SHADOW or PAPER rebalance for the full portfolio. Goal slices do not create separate orders."
        confirmLabel="Apply one combined target"
        requireReason={false}
        danger={false}
        pending={applyMutation.isPending}
        onClose={() => setConfirmOpen(false)}
        onConfirm={async () => { await applyMutation.mutateAsync() }}
      />
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

function GoalSelections({goal, instruments}: {goal: PortfolioGoalAllocation; instruments: Instrument[]}) {
  const queryClient = useQueryClient()
  const eligibility = useQuery(queries.constructionEligibility(goal.id))
  const policies = useQuery(queries.strategyPolicies())
  const stocks = useQuery(queries.constructionInstruments(goal.id))
  const [ticker, setTicker] = useState('')
  const [resolution, setResolution] = useState<InstrumentResolution | null>(null)
  const [generatedRecommendation, setGeneratedRecommendation] = useState<GoalRecommendationRun | null>(null)
  const recommendationId = generatedRecommendation?.id || goal.accepted_recommendation_run_id
  const recommendationQuery = useQuery(queries.recommendation(recommendationId))
  const recommendation = recommendationQuery.data || generatedRecommendation
  const mvp = useQuery(queries.researchMVPStatus())
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({queryKey: ['construction-instruments', goal.id]}),
      queryClient.invalidateQueries({queryKey: ['construction-plans']}),
      queryClient.invalidateQueries({queryKey: ['goal-recommendation']}),
    ])
  }
  const generateRecommendation = useMutation({
    mutationFn: async () => pollRecommendation(await request<GoalRecommendationRun>(
      `portfolio-construction/goals/${goal.id}/recommendations/`, mutationOptions('POST', {}, true),
    )),
    onSuccess: (run) => setGeneratedRecommendation(run),
  })
  const acceptRecommendation = useMutation({
    mutationFn: () => request<{created: boolean; acceptance_id: number; recommendation: GoalRecommendationRun}>(
      `portfolio-construction/recommendations/${recommendation?.id}/accept/`, mutationOptions('POST', {}),
    ),
    onSuccess: async (result) => {setGeneratedRecommendation(result.recommendation); await refresh()},
  })
  const detachRecommendation = useMutation({
    mutationFn: () => request<{goal_id: number}>(
      `portfolio-construction/goals/${goal.id}/detach-recommendation/`, mutationOptions('POST', {}),
    ),
    onSuccess: async () => {setGeneratedRecommendation(null); await refresh()},
  })
  const add = useMutation({
    mutationFn: () => {
      if (!resolution?.instrument_id) throw new Error('Qualify an exact IBKR stock contract first')
      return request<GoalInstrumentSelection>(`portfolio-construction/goals/${goal.id}/instruments/`, mutationOptions('POST', {
        instrument_id: resolution.instrument_id,
      }))
    },
    onSuccess: async () => {setTicker(''); setResolution(null); await refresh()},
  })
  const remove = useMutation({
    mutationFn: (stockId: number) => request<{id: number}>(`portfolio-construction/instruments/${stockId}/`, mutationOptions('DELETE')),
    onSuccess: refresh,
  })
  if (goal.timeframe_bucket === 'NOW') return <section className="goal-selection-card"><header><div><h3>{goal.name}</h3><p>{formatPercent(goal.allocation_weight)} · {goal.resolved_rules.timeframe_label} · {goal.resolved_rules.risk_label}</p></div><StatusBadge status="CASH ONLY" /></header><p className="inline-note">NOW goals are intentionally 100% cash and do not accept stocks or strategy assignments.</p></section>
  const manual = goalAllowsManualEdits(goal)
  return <section className="goal-selection-card">
    <header><div><h3>{goal.name}</h3><p>{formatPercent(goal.allocation_weight)} · {goal.resolved_rules.timeframe_label} · {goal.resolved_rules.risk_label}</p></div><StatusBadge status={manual ? `${stocks.data?.length || 0} STOCKS` : 'RECOMMENDATION LOCKED'} /></header>
    <div className="recommendation-panel">
      <div className="apply-summary"><StatusBadge status={recommendation?.status || (manual ? 'MANUAL MODE' : 'ACCEPTED')} /><div><strong>{manual ? 'Research recommendation' : `Accepted recommendation ${goal.accepted_recommendation_run_id}`}</strong><span>{recommendation ? `Dataset ${recommendation.dataset_version_id} · Protocol ${recommendation.protocol_version_id} · expires ${new Date(recommendation.expires_at).toLocaleString()}` : 'Approved candidates and exact broker-qualified stocks only.'}</span></div></div>
      <p className="field-help">Readiness: {mvp.data ? `${mvp.data.ready_stock_count}/5 stocks · ${mvp.data.completed_experiment_groups}/25 backtests · ${mvp.data.eligible_candidate_count} eligible scores` : 'checking…'}</p>
      {recommendation?.sleeves?.length ? <div className="goal-stock-list">{recommendation.sleeves.map((sleeve) => <div className="goal-stock-card" key={sleeve.id}><strong>{sleeve.symbol} · {formatPercent(sleeve.stock_weight)}</strong><span>{sleeve.gics.sector?.name} / {sleeve.gics.industry?.name}</span><p>{sleeve.strategy_name} · {formatPercent(sleeve.strategy_share)} share · score {formatNumber(sleeve.candidate_score)}</p><p className="field-help">Expected return {formatPercent(sleeve.expected_return)} · volatility {formatPercent(sleeve.expected_volatility)} · drawdown {formatPercent(sleeve.expected_drawdown)}. {sleeve.rationale}</p><p className="field-help">Data {sleeve.data_source || 'unknown'} · latest {sleeve.latest_data_date || 'unavailable'}</p></div>)}</div> : null}
      {recommendation?.warnings?.length ? <div className={recommendation.status === 'BLOCKED' ? 'inline-warning' : 'inline-note'}><div><strong>{recommendation.status === 'BLOCKED' ? 'Recommendation blocked' : 'Recommendation notes'}</strong><p>{recommendationBlockerText(recommendation)}</p></div></div> : null}
      <div className="system-actions">
        {manual && <button className="button-secondary" disabled={generateRecommendation.isPending} onClick={() => generateRecommendation.mutate()}>{generateRecommendation.isPending ? 'Generating…' : recommendation ? 'Regenerate' : 'Generate recommendation'}</button>}
        {recommendation && recommendationCanBeAccepted(recommendation) && <button className="button-primary" disabled={acceptRecommendation.isPending} onClick={() => acceptRecommendation.mutate()}>{acceptRecommendation.isPending ? 'Accepting…' : 'Accept recommendation'}</button>}
        {!manual && <button className="button-secondary" disabled={detachRecommendation.isPending} onClick={() => detachRecommendation.mutate()}>{detachRecommendation.isPending ? 'Detaching…' : 'Detach recommendation'}</button>}
      </div>
      {(generateRecommendation.isError || acceptRecommendation.isError || detachRecommendation.isError || recommendationQuery.isError) && <ErrorState title="Recommendation action was blocked" error={generateRecommendation.error || acceptRecommendation.error || detachRecommendation.error || recommendationQuery.error} compact />}
      {!manual && <p className="inline-note">Accepted weights and strategy shares are immutable. Detach before manual edits; preview and apply remain mandatory separate steps.</p>}
    </div>
    {manual && (eligibility.isLoading || policies.isLoading || stocks.isLoading ? <Skeleton lines={3} /> : eligibility.isError || policies.isError || stocks.isError ? <ErrorState error={eligibility.error || policies.error || stocks.error} compact /> : <>
      <div className="add-goal-stock"><BrokerInstrumentSearch value={ticker} suggestions={instruments} searchLabel={`${goal.name} IBKR stock search`} onValueChange={setTicker} onResolved={setResolution} /><button className="button-secondary" disabled={add.isPending || !resolution?.instrument_id} onClick={() => add.mutate()}><Plus />Add stock</button></div>
      {add.isError && <ErrorState error={add.error} compact />}
      <div className="goal-stock-list">{(stocks.data || []).map((stock) => <section className="goal-stock-card" key={stock.id}><header><div><strong>{stock.symbol}</strong><span>{stock.exchange} · {stock.currency}</span></div><button className="icon-button" aria-label={`Remove ${stock.symbol} from ${goal.name}`} disabled={remove.isPending} onClick={() => remove.mutate(stock.id)}><Trash2 /></button></header><StockAssignments stock={stock} strategies={eligibility.data?.eligible || []} policies={policies.data} /></section>)}</div>
      {!stocks.data?.length && <p className="inline-note">Add a qualified stock to define this goal's optimizer universe.</p>}
      <details className="rejected-strategies"><summary>{eligibility.data?.rejected.length || 0} strategies not eligible</summary><ul>{eligibility.data?.rejected.map((item) => <li key={item.strategy_definition_id}><strong>{item.name}</strong><span>{item.reason}</span></li>)}</ul></details>
    </>)}
  </section>
}

function StockAssignments({stock, strategies, policies}: {stock: GoalInstrumentSelection; strategies: ConstructionStrategyOption[]; policies?: StrategyPolicies}) {
  const queryClient = useQueryClient()
  const assignments = useQuery(queries.constructionAssignments(stock.id))
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({queryKey: ['construction-assignments', stock.id]}),
      queryClient.invalidateQueries({queryKey: ['construction-instruments', stock.goal_id]}),
      queryClient.invalidateQueries({queryKey: ['construction-plans']}),
    ])
  }
  const owners = (assignments.data || []).filter((item) => item.enabled && item.create_instance)
  const total = owners.reduce((sum, item) => sum + toNumber(item.strategy_share), 0)
  const valid = owners.length > 0 && Math.abs(total - 1) < 0.00000001
  if (assignments.isLoading) return <Skeleton lines={2} />
  if (assignments.isError) return <ErrorState error={assignments.error} compact />
  return <div className="stock-assignments"><div className={valid ? 'positive-text' : 'field-error'}>{owners.length ? `Strategy ownership: ${formatPercent(total)}` : 'Add at least one strategy assignment'}{!valid && owners.length > 0 ? ' · must total 100%' : ''}</div>
    {(assignments.data || []).map((assignment) => <AssignmentEditor key={assignment.id} assignment={assignment} strategies={strategies} policies={policies} onSaved={refresh} />)}
    <NewAssignmentEditor stock={stock} strategies={strategies} policies={policies} hasOwners={owners.length > 0} onSaved={refresh} />
  </div>
}

type AssignmentDraft = {
  strategyDefinitionId: number | ''
  timeframe: string
  parameters: Record<string, Scalar>
  sharePercentage: string
  riskPolicyId: string
  orderPolicyId: string
  createInstance: boolean
  enabled: boolean
}

function assignmentPayload(draft: AssignmentDraft) {
  return {
    strategy_definition_id: draft.strategyDefinitionId,
    execution_timeframe: draft.timeframe,
    parameter_overrides: {...draft.parameters, direction: 'LONG'},
    strategy_share: Number(draft.sharePercentage) / 100,
    risk_policy_id: draft.riskPolicyId ? Number(draft.riskPolicyId) : null,
    order_policy_id: draft.orderPolicyId ? Number(draft.orderPolicyId) : null,
    create_instance: draft.createInstance,
    enabled: draft.enabled,
  }
}

function NewAssignmentEditor({stock, strategies, policies, hasOwners, onSaved}: {stock: GoalInstrumentSelection; strategies: ConstructionStrategyOption[]; policies?: StrategyPolicies; hasOwners: boolean; onSaved: () => Promise<void>}) {
  const first = strategies[0]
  const [draft, setDraft] = useState<AssignmentDraft>(() => ({
    strategyDefinitionId: first?.strategy_definition_id || '',
    timeframe: first?.execution_timeframes[0] || '',
    parameters: {...(first?.default_parameters || {}), direction: 'LONG'},
    sharePercentage: hasOwners ? '' : '100', riskPolicyId: '', orderPolicyId: '', createInstance: true, enabled: true,
  }))
  const strategy = strategies.find((item) => item.strategy_definition_id === draft.strategyDefinitionId)
  const create = useMutation({
    mutationFn: () => {
      if (!draft.strategyDefinitionId || !draft.timeframe || draft.sharePercentage === '') throw new Error('Choose a strategy, timeframe, and explicit ownership share')
      return request<GoalStrategyAssignment>(`portfolio-construction/instruments/${stock.id}/assignments/`, mutationOptions('POST', assignmentPayload(draft)))
    },
    onSuccess: async () => {
      setDraft((current) => ({...current, sharePercentage: ''}))
      await onSaved()
    },
  })
  return <details className="assignment-editor"><summary><Plus />Assign strategy</summary><AssignmentFields draft={draft} setDraft={setDraft} strategies={strategies} strategy={strategy} policies={policies} prefix={`New ${stock.symbol} `} /><button className="button-secondary" disabled={create.isPending} onClick={() => create.mutate()}>Add assignment</button>{create.isError && <ErrorState error={create.error} compact />}</details>
}

function AssignmentEditor({assignment, strategies, policies, onSaved}: {assignment: GoalStrategyAssignment; strategies: ConstructionStrategyOption[]; policies?: StrategyPolicies; onSaved: () => Promise<void>}) {
  const [draft, setDraft] = useState<AssignmentDraft>(() => ({
    strategyDefinitionId: assignment.strategy_definition_id,
    timeframe: assignment.execution_timeframe,
    parameters: assignment.parameter_overrides as Record<string, Scalar>,
    sharePercentage: String(toNumber(assignment.strategy_share) * 100),
    riskPolicyId: assignment.risk_policy_id ? String(assignment.risk_policy_id) : '',
    orderPolicyId: assignment.order_policy_id ? String(assignment.order_policy_id) : '',
    createInstance: assignment.create_instance,
    enabled: assignment.enabled,
  }))
  const strategy = strategies.find((item) => item.strategy_definition_id === draft.strategyDefinitionId)
  const save = useMutation({
    mutationFn: () => request<GoalStrategyAssignment>(`portfolio-construction/assignments/${assignment.id}/`, mutationOptions('PATCH', assignmentPayload(draft))),
    onSuccess: onSaved,
  })
  const remove = useMutation({
    mutationFn: () => request<{id: number}>(`portfolio-construction/assignments/${assignment.id}/`, mutationOptions('DELETE')),
    onSuccess: onSaved,
  })
  return <details className="assignment-editor" open><summary><strong>{assignment.strategy_name}</strong><span>{formatPercent(assignment.strategy_share)} · {assignment.execution_timeframe}</span>{assignment.created_strategy_instance_id && <Link to={`/strategies/${assignment.created_strategy_instance_id}`}>Strategy {assignment.created_strategy_instance_id}</Link>}</summary><AssignmentFields draft={draft} setDraft={setDraft} strategies={strategies} strategy={strategy} policies={policies} prefix={`${assignment.symbol} ${assignment.strategy_name} `} /><div className="system-actions"><button className="button-secondary" disabled={save.isPending} onClick={() => save.mutate()}>Save assignment</button><button className="icon-button" aria-label={`Remove ${assignment.strategy_name} from ${assignment.symbol}`} disabled={remove.isPending} onClick={() => remove.mutate()}><Trash2 /></button></div>{(save.isError || remove.isError) && <ErrorState error={save.error || remove.error} compact />}</details>
}

function AssignmentFields({draft, setDraft, strategies, strategy, policies, prefix}: {draft: AssignmentDraft; setDraft: React.Dispatch<React.SetStateAction<AssignmentDraft>>; strategies: ConstructionStrategyOption[]; strategy?: ConstructionStrategyOption; policies?: StrategyPolicies; prefix: string}) {
  const selectStrategy = (id: number) => {
    const selected = strategies.find((item) => item.strategy_definition_id === id)
    setDraft((current) => ({...current, strategyDefinitionId: id, timeframe: selected?.execution_timeframes[0] || '', parameters: {...(selected?.default_parameters || {}), direction: 'LONG'}}))
  }
  return <div className="assignment-fields"><div className="form-grid three-columns"><label>Strategy<select aria-label={`${prefix}strategy`} value={draft.strategyDefinitionId} onChange={(event) => selectStrategy(Number(event.target.value))}>{strategies.map((item) => <option key={item.strategy_definition_id} value={item.strategy_definition_id}>{item.name}</option>)}</select></label><label>Execution timeframe<select aria-label={`${prefix}execution timeframe`} value={draft.timeframe} onChange={(event) => setDraft((current) => ({...current, timeframe: event.target.value}))}>{(strategy?.execution_timeframes || []).map((item) => <option key={item}>{item}</option>)}</select></label><label>Strategy share %<input aria-label={`${prefix}strategy share`} type="number" min="0" max="100" step="0.000001" value={draft.sharePercentage} onChange={(event) => setDraft((current) => ({...current, sharePercentage: event.target.value}))} /></label><label>Risk policy<select aria-label={`${prefix}risk policy`} value={draft.riskPolicyId} onChange={(event) => setDraft((current) => ({...current, riskPolicyId: event.target.value}))}><option value="">Default</option>{(policies?.risk_policies || []).filter((item) => !item.allow_short).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Order policy<select aria-label={`${prefix}order policy`} value={draft.orderPolicyId} onChange={(event) => setDraft((current) => ({...current, orderPolicyId: event.target.value}))}><option value="">Default</option>{(policies?.order_policies || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label className="goal-enabled"><input type="checkbox" checked={draft.createInstance} onChange={(event) => setDraft((current) => ({...current, createInstance: event.target.checked}))} />Create instance</label></div>{strategy && <><p className="field-help">{strategy.summary} {strategy.limitations}</p><SchemaParameterForm schema={strategy.parameter_schema} values={draft.parameters} fixedValues={{direction: 'LONG'}} ariaPrefix={prefix} onChange={(parameters) => setDraft((current) => ({...current, parameters}))} /></>}</div>
}

function PreviewStep({run, onBack, onContinue}: {run: PortfolioConstructionRun | null; onBack: () => void; onContinue: () => void}) {
  if (!run) return <TerminalPanel id="construction-preview-empty" title="3. Preview" description="Construct every goal before reviewing the combined portfolio." collapsible={false}><EmptyState title="No preview yet" /><button className="button-secondary" onClick={onBack}>Back to stocks and assignments</button></TerminalPanel>
  const targets = run.targets || []
  return <TerminalPanel id="construction-preview" title="3. Preview" description="Local goal targets are weighted and merged into one final portfolio target and one net trade list." collapsible={false}>
    <section className="metric-grid compact">
      <TerminalMetric label="Expected return" value={formatPercent(run.metrics.expected_return)} />
      <TerminalMetric label="Expected volatility" value={formatPercent(run.metrics.expected_volatility)} />
      <TerminalMetric label="Sharpe ratio" value={formatNumber(run.metrics.sharpe_ratio)} />
      <TerminalMetric label="Combined cash" value={formatPercent(run.final_target_weights.cash)} />
      <TerminalMetric label="Net turnover" value={formatPercent(run.rebalance?.planned_turnover)} />
      <TerminalMetric label="Planner" value={<StatusBadge status={run.rebalance?.mode || 'SHADOW'} />} />
    </section>
    <div className="goal-preview-grid">{(run.goals || []).map((goal) => <section key={goal.goal_id} className="goal-preview-card"><header><div><h3>{goal.name}</h3><p>{formatPercent(goal.allocation_weight)} · {goal.timeframe_bucket} · Risk {goal.risk_level}{goal.accepted_recommendation_run_id ? ` · Recommendation ${goal.accepted_recommendation_run_id}` : ''}</p></div><StatusBadge status={goal.construction_source === 'ACCEPTED_RECOMMENDATION' ? 'FIXED RECOMMENDATION' : goal.optimizer_method || 'CASH ONLY'} /></header><div className="goal-preview-cash"><span>Cash inside goal</span><strong>{formatPercent(goal.cash_weight)}</strong></div><ul>{goal.stocks.map((stock) => <li key={stock.instrument_id}><strong>{stock.symbol}</strong><span>{formatPercent(stock.local_weight)} {goal.construction_source === 'ACCEPTED_RECOMMENDATION' ? 'fixed ' : ''}local stock weight · {formatPercent(stock.portfolio_contribution)} complete-portfolio stock contribution</span><ul>{stock.strategies.map((strategy) => <li key={strategy.assignment_id}><span>{strategy.strategy_name} · {formatPercent(strategy.strategy_share)} share · {formatPercent(strategy.portfolio_weight)} strategy-controlled portfolio weight</span></li>)}</ul>{!stock.strategy_share_valid && <span className="field-error">Strategy shares total {formatPercent(stock.strategy_share_total)}; 100% is required.</span>}</li>)}</ul>{!goal.stocks.length && <p className="inline-note">Cash-only target</p>}{goal.warnings.length > 0 && <p className="field-help">{goal.warnings.map((item) => item.message || item.code).join(' · ')}</p>}</section>)}</div>
    <div><h3>Aggregated strategy instance targets</h3><DataTable rows={run.metrics.strategy_targets || []} columns={[
      {id: 'strategy', header: 'Strategy', cell: (item) => <div className="primary-cell"><strong>{item.strategy_name}</strong><span>{item.symbol} · {item.execution_timeframe}</span></div>},
      {id: 'assignments', header: 'Assignments', align: 'right' as const, cell: (item) => formatNumber(item.assignment_ids.length)},
      {id: 'target', header: 'Aggregated target', align: 'right' as const, cell: (item) => formatPercent(item.target_weight)},
    ]} getRowKey={(item) => item.identity} emptyTitle="No strategy-owned stock weight" /></div>
    <div><h3>Final combined allocation</h3><DataTable rows={targets} columns={[
      {id: 'stock', header: 'Stock', cell: (item) => <div className="primary-cell"><strong className="mono">{item.symbol}</strong>{item.shared_across_goals && <span>Shared by {item.goal_contributions.length} goals</span>}</div>},
      {id: 'current', header: 'Current', align: 'right' as const, cell: (item) => formatPercent(item.current_weight)},
      {id: 'target', header: 'Proposed', align: 'right' as const, cell: (item) => formatPercent(item.target_weight)},
      {id: 'value', header: 'Target value', align: 'right' as const, cell: (item) => formatMoney(item.target_value)},
      {id: 'goals', header: 'Goal contributions', cell: (item) => item.goal_contributions.map((value) => `${value.goal_name} ${formatPercent(value.portfolio_contribution)}`).join(' · ')},
    ]} getRowKey={(item) => item.id} emptyTitle="Cash-only combined target" /></div>
    <div><h3>One net rebalance</h3><DataTable rows={run.planned_trades || []} columns={[
      {id: 'stock', header: 'Stock', cell: (item) => <strong className="mono">{item.symbol}</strong>},
      {id: 'weights', header: 'Current → target', cell: (item) => `${formatPercent(item.current_weight)} → ${formatPercent(item.target_weight)}`},
      {id: 'side', header: 'Side', cell: (item) => <StatusBadge status={item.side} />},
      {id: 'quantity', header: 'Quantity', align: 'right' as const, cell: (item) => formatNumber(item.quantity)},
      {id: 'state', header: 'State', cell: (item) => <StatusBadge status={item.suppressed ? item.suppression_reason || 'SUPPRESSED' : 'PLANNED'} />},
    ]} getRowKey={(item) => item.instrument_id} emptyTitle="No net trades required" /></div>
    {run.warnings.length > 0 && <div className="inline-warning"><StatusBadge status="WARNING" /><p>{formatCompact(run.warnings)}</p></div>}
    <div className="system-actions"><button className="button-secondary" onClick={onBack}>Back to stocks and assignments</button><button className="button-primary" onClick={onContinue}>Continue to apply</button></div>
  </TerminalPanel>
}
