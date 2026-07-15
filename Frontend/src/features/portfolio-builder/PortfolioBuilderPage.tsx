import {useEffect, useMemo, useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {Check, Plus, Trash2} from 'lucide-react'
import {Link} from 'react-router-dom'

import {API_BASE_URL, mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {
  GoalStrategySelection,
  GoalTimeframe,
  Instrument,
  PortfolioConstructionPlan,
  PortfolioConstructionRun,
  PortfolioGoalAllocation,
} from '../../api/types'
import {
  ConfirmActionDialog,
  DataTable,
  EmptyState,
  ErrorState,
  MetricCard,
  PageHeader,
  Panel,
  Skeleton,
  StatusBadge,
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

  if (!selectedPortfolioId) return <EmptyState title="Select a portfolio" description="Portfolio Builder needs one broker-backed portfolio context." />
  if (plans.isLoading) return <Skeleton lines={7} />
  if (plans.isError) return <ErrorState title="Portfolio Builder is unavailable" error={plans.error} onRetry={() => void plans.refetch()} />

  return <div className="page-stack portfolio-builder">
    <PageHeader
      eyebrow="Deterministic construction"
      title="Portfolio Builder"
      description="Divide one portfolio into goal slices, construct each slice independently, and apply one combined paper-only rebalance."
    />
    {!plan ? <Panel title="Create a construction plan" description="One plan organizes up to ten virtual goals for this portfolio.">
      <button className="button-primary" disabled={createPlan.isPending} onClick={() => createPlan.mutate()}>{createPlan.isPending ? 'Creating…' : 'Start Portfolio Builder'}</button>
      {createPlan.isError && <ErrorState error={createPlan.error} compact />}
    </Panel> : <>
      <ol className="builder-steps" aria-label="Portfolio Builder steps">
        {['Allocate goals', 'Select strategies & stocks', 'Preview', 'Apply'].map((label, index) => {
          const number = index + 1
          return <li key={label} className={step === number ? 'active' : step > number ? 'complete' : ''}>
            <button type="button" onClick={() => number <= step && setStep(number)}><span>{step > number ? <Check /> : number}</span><strong>{label}</strong></button>
          </li>
        })}
      </ol>
      {step === 1 && <Panel title="1. Allocate goals" description="Draft percentages may be incomplete while editing; continuing requires exactly 100%.">
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
      </Panel>}
      {step === 2 && <Panel title="2. Select strategies and stocks" description="Selections are stored separately for every goal. Rejected strategies remain visible with a reason.">
        <div className="goal-selection-list">
          {plan.goals.filter((goal) => goal.enabled).map((goal) => <GoalSelections key={goal.id} goal={goal} instruments={stockInstruments} />)}
        </div>
        <div className="system-actions">
          <button className="button-secondary" onClick={() => setStep(1)}>Back to allocations</button>
          <button className="button-primary" disabled={!plan.ready_to_preview || previewMutation.isPending} onClick={() => previewMutation.mutate()}>{previewMutation.isPending ? 'Constructing goals…' : 'Preview combined portfolio'}</button>
        </div>
        {previewMutation.isError && <ErrorState title="Construction preview failed" error={previewMutation.error} compact />}
      </Panel>}
      {step === 3 && <PreviewStep run={shownPreview} onBack={() => setStep(2)} onContinue={() => setStep(4)} />}
      {step === 4 && <Panel title="4. Apply once" description={`Apply one combined target through the existing ${system.data?.execution_mode || 'SHADOW'} rebalance and execution safety pipeline.`}>
        {!shownPreview ? <EmptyState title="No completed preview" description="Return to step 2 and preview the construction first." /> : <>
          <div className="apply-summary">
            <StatusBadge status={shownPreview.application_status} />
            <div><strong>Construction run {shownPreview.id}</strong><span>{shownPreview.targets?.length || 0} merged stock targets · {shownPreview.goals?.length || 0} goals</span></div>
          </div>
          {shownPreview.applied_rebalance ? <div className="inline-success"><StatusBadge status={shownPreview.applied_rebalance.status} /><div><strong>Applied through rebalance {shownPreview.applied_rebalance.id}</strong><p>Strategy instances were left disabled in SHADOW mode for manual review.</p><div className="inline-links"><a href={`${API_BASE_URL}/portfolio-construction/runs/${shownPreview.id}/`} target="_blank" rel="noreferrer">Construction run {shownPreview.id}</a><a href={`${API_BASE_URL}/rebalancing/runs/${shownPreview.applied_rebalance.id}/`} target="_blank" rel="noreferrer">Rebalance {shownPreview.applied_rebalance.id}</a>{shownPreview.metrics.strategy_instances?.map((item) => <Link key={item.strategy_instance_id} to={`/strategies/${item.strategy_instance_id}`}>Strategy {item.strategy_instance_id}</Link>)}<Link to="/portfolio">View portfolio</Link><Link to="/strategies">Review strategies</Link><Link to="/activity">Orders & activity</Link></div></div></div> : <div className="system-actions"><button className="button-secondary" onClick={() => setStep(3)}>Back to preview</button><button className="button-primary" disabled={Boolean(shownPreview.goals?.some((goal) => goal.apply_blocked)) || applyMutation.isPending} onClick={() => setConfirmOpen(true)}>Apply combined target</button></div>}
          {shownPreview.goals?.some((goal) => goal.apply_blocked) && <div className="inline-warning"><StatusBadge status="BLOCKED" /><p>Add at least one stock to every non-NOW goal before applying.</p></div>}
          {applyMutation.isError && <ErrorState title="Construction application was blocked" error={applyMutation.error} compact />}
        </>}
      </Panel>}
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
  const selections = useQuery(queries.constructionSelections(goal.id))
  const [strategyId, setStrategyId] = useState<number | ''>('')
  const [instrumentId, setInstrumentId] = useState<number | ''>('')
  const [timeframe, setTimeframe] = useState('')
  const strategies = eligibility.data?.eligible || []
  const strategy = strategies.find((item) => item.strategy_definition_id === strategyId)
  useEffect(() => {
    if (!strategyId && strategies[0]) setStrategyId(strategies[0].strategy_definition_id)
  }, [strategyId, strategies])
  useEffect(() => {
    const selected = strategies.find((item) => item.strategy_definition_id === strategyId)
    if (selected && !selected.execution_timeframes.includes(timeframe)) setTimeframe(selected.execution_timeframes[0] || '')
  }, [strategyId, strategies, timeframe])
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({queryKey: ['construction-selections', goal.id]}),
      queryClient.invalidateQueries({queryKey: ['construction-plans']}),
    ])
  }
  const add = useMutation({
    mutationFn: () => {
      if (!strategy || !instrumentId || !timeframe) throw new Error('Choose a strategy, stock, and execution timeframe')
      return request<GoalStrategySelection>(`portfolio-construction/goals/${goal.id}/selections/`, mutationOptions('POST', {
        strategy_definition_id: strategy.strategy_definition_id,
        instrument_id: instrumentId,
        execution_timeframe: timeframe,
        parameter_overrides: {...strategy.default_parameters, direction: 'LONG'},
      }))
    },
    onSuccess: refresh,
  })
  const remove = useMutation({
    mutationFn: (selectionId: number) => request<{id: number}>(`portfolio-construction/selections/${selectionId}/`, mutationOptions('DELETE')),
    onSuccess: refresh,
  })
  if (goal.timeframe_bucket === 'NOW') return <section className="goal-selection-card"><header><div><h3>{goal.name}</h3><p>{formatPercent(goal.allocation_weight)} · {goal.resolved_rules.timeframe_label} · {goal.resolved_rules.risk_label}</p></div><StatusBadge status="CASH ONLY" /></header><p className="inline-note">NOW goals are intentionally 100% cash and do not accept strategy-stock selections.</p></section>
  return <section className="goal-selection-card">
    <header><div><h3>{goal.name}</h3><p>{formatPercent(goal.allocation_weight)} · {goal.resolved_rules.timeframe_label} · {goal.resolved_rules.risk_label}</p></div><StatusBadge status={`${selections.data?.length || 0} SELECTED`} /></header>
    {eligibility.isLoading || selections.isLoading ? <Skeleton lines={3} /> : eligibility.isError || selections.isError ? <ErrorState error={eligibility.error || selections.error} compact /> : <>
      <div className="form-grid three-columns">
        <label>Strategy<select aria-label={`${goal.name} strategy`} value={strategyId} onChange={(event) => setStrategyId(Number(event.target.value))}>{strategies.map((item) => <option key={item.strategy_definition_id} value={item.strategy_definition_id}>{item.name}</option>)}</select></label>
        <label>Stock<select aria-label={`${goal.name} stock`} value={instrumentId} onChange={(event) => setInstrumentId(Number(event.target.value))}><option value="">Choose a stock</option>{instruments.map((item) => <option key={item.id} value={item.id}>{item.symbol} · {item.sector || item.exchange}</option>)}</select></label>
        <label>Execution timeframe<select aria-label={`${goal.name} execution timeframe`} value={timeframe} onChange={(event) => setTimeframe(event.target.value)}>{(strategy?.execution_timeframes || []).map((item) => <option key={item}>{item}</option>)}</select></label>
      </div>
      {strategy && <p className="field-help">{strategy.summary} {strategy.limitations}</p>}
      <button className="button-secondary" disabled={add.isPending || !strategy || !instrumentId || !timeframe} onClick={() => add.mutate()}><Plus />Add strategy-stock pair</button>
      {add.isError && <ErrorState error={add.error} compact />}
      <ul className="selection-chips">{(selections.data || []).map((item) => <li key={item.id}><div><strong>{item.symbol}</strong><span>{item.strategy_name} · {item.execution_timeframe}</span></div><button className="icon-button" aria-label={`Remove ${item.strategy_name} ${item.symbol}`} disabled={remove.isPending} onClick={() => remove.mutate(item.id)}><Trash2 /></button></li>)}</ul>
      <details className="rejected-strategies"><summary>{eligibility.data?.rejected.length || 0} strategies not eligible</summary><ul>{eligibility.data?.rejected.map((item) => <li key={item.strategy_definition_id}><strong>{item.name}</strong><span>{item.reason}</span></li>)}</ul></details>
    </>}
  </section>
}

function PreviewStep({run, onBack, onContinue}: {run: PortfolioConstructionRun | null; onBack: () => void; onContinue: () => void}) {
  if (!run) return <Panel title="3. Preview" description="Construct every goal before reviewing the combined portfolio."><EmptyState title="No preview yet" /><button className="button-secondary" onClick={onBack}>Back to selections</button></Panel>
  const targets = run.targets || []
  return <Panel title="3. Preview" description="Local goal targets are weighted and merged into one final portfolio target and one net trade list.">
    <section className="metric-grid compact">
      <MetricCard label="Expected return" value={formatPercent(run.metrics.expected_return)} />
      <MetricCard label="Expected volatility" value={formatPercent(run.metrics.expected_volatility)} />
      <MetricCard label="Sharpe ratio" value={formatNumber(run.metrics.sharpe_ratio)} />
      <MetricCard label="Combined cash" value={formatPercent(run.final_target_weights.cash)} />
      <MetricCard label="Net turnover" value={formatPercent(run.rebalance?.planned_turnover)} />
      <MetricCard label="Planner" value={<StatusBadge status={run.rebalance?.mode || 'SHADOW'} />} />
    </section>
    <div className="goal-preview-grid">{(run.goals || []).map((goal) => <section key={goal.goal_id} className="goal-preview-card"><header><div><h3>{goal.name}</h3><p>{formatPercent(goal.allocation_weight)} · {goal.timeframe_bucket} · Risk {goal.risk_level}</p></div><StatusBadge status={goal.optimizer_method || 'CASH ONLY'} /></header><div className="goal-preview-cash"><span>Cash inside goal</span><strong>{formatPercent(goal.cash_weight)}</strong></div><ul>{goal.stocks.map((stock) => <li key={stock.instrument_id}><strong>{stock.symbol}</strong><span>{formatPercent(stock.local_weight)} local · {formatPercent(stock.portfolio_contribution)} portfolio</span></li>)}</ul>{!goal.stocks.length && <p className="inline-note">Cash-only target</p>}{goal.warnings.length > 0 && <p className="field-help">{goal.warnings.map((item) => item.message || item.code).join(' · ')}</p>}</section>)}</div>
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
    <div className="system-actions"><button className="button-secondary" onClick={onBack}>Back to selections</button><button className="button-primary" onClick={onContinue}>Continue to apply</button></div>
  </Panel>
}
