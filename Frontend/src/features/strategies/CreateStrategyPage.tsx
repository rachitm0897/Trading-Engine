import {useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {ArrowLeft, ArrowRight, Check, CircleCheck, ShieldCheck} from 'lucide-react'
import {Link, useNavigate} from 'react-router-dom'
import {mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {InstrumentResolution, Scalar, StrategyDefinition, StrategyInstance} from '../../api/types'
import {BrokerInstrumentSearch} from '../../components/BrokerInstrumentSearch'
import {SchemaParameterForm} from '../../components/SchemaParameterForm'
import {CollapsibleSection, ErrorState, PageHeader, Panel, Skeleton, StatusBadge, formatCompact} from '../../components/ui'
import {useSelection} from '../../stores/useSelection'

const steps = ['Instrument', 'Definition', 'Parameters', 'Risk & execution', 'Review']

interface Draft {
  ticker: string
  exchange: string
  name: string
  definitionKey: string
  timeframe: string
  parameters: Record<string, Scalar>
  targetWeight: string
  capitalShare: string
  priority: string
  riskPolicyId: string
  orderPolicyId: string
  executionMode: 'SHADOW' | 'OBSERVE' | 'PAPER'
}

const initialDraft: Draft = {
  ticker: '', exchange: 'SMART', name: '', definitionKey: '', timeframe: '', parameters: {},
  targetWeight: '0.05', capitalShare: '1', priority: '100', riskPolicyId: '', orderPolicyId: '', executionMode: 'SHADOW',
}

export function CreateStrategyPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const {selectedPortfolioId, portfolio} = useSelection()
  const definitions = useQuery(queries.strategyDefinitions())
  const instruments = useQuery(queries.instruments())
  const policies = useQuery(queries.strategyPolicies())
  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState<Draft>(initialDraft)
  const [validation, setValidation] = useState<string | null>(null)
  const [resolution, setResolution] = useState<InstrumentResolution | null>(null)
  const definition = definitions.data?.find((item) => item.key === draft.definitionKey) || null
  const create = useMutation({
    mutationFn: () => request<StrategyInstance>('strategy-instances/', mutationOptions('POST', {
      name: draft.name.trim(), definition_key: draft.definitionKey, instrument_id: resolution?.instrument_id,
      portfolio_id: selectedPortfolioId, timeframe: draft.timeframe, parameters: draft.parameters,
      target_configuration: {target_weight: Number(draft.targetWeight), capital_share: Number(draft.capitalShare), priority: Number(draft.priority)},
      risk_policy_id: draft.riskPolicyId ? Number(draft.riskPolicyId) : null,
      order_policy_id: draft.orderPolicyId ? Number(draft.orderPolicyId) : null,
      execution_mode: draft.executionMode, qualify: false,
    }, true)),
    onSuccess: async (data) => {
      await queryClient.invalidateQueries({queryKey: ['strategy-instances']})
      navigate(`/strategies/${data.id}`)
    },
  })

  const selectDefinition = (key: string) => {
    const selected = definitions.data?.find((item) => item.key === key)
    setDraft((current) => ({...current, definitionKey: key, timeframe: selected?.supported_timeframes[0] || '', parameters: {...(selected?.default_parameters || {})}}))
  }
  const validateStep = () => {
    let error = ''
    if (step === 0 && !draft.ticker.trim()) error = 'Enter a ticker before continuing.'
    else if (step === 0 && !resolution?.conid) error = 'Select and qualify an exact IBKR contract before continuing.'
    if (step === 1 && (!draft.name.trim() || !draft.definitionKey || !draft.timeframe)) error = 'Choose a definition and timeframe, and name this instance.'
    if (step === 2 && definition) {
      const missing = (definition.parameter_schema.required || []).filter((key) => draft.parameters[key] === undefined || draft.parameters[key] === null || draft.parameters[key] === '')
      if (missing.length) error = `Complete required parameters: ${missing.join(', ')}.`
    }
    if (step === 3 && (!Number.isFinite(Number(draft.targetWeight)) || Number(draft.capitalShare) < 0 || Number(draft.capitalShare) > 1 || Number(draft.priority) < 1)) error = 'Review target, capital share, and priority values.'
    setValidation(error || null)
    return !error
  }
  const next = () => { if (validateStep()) setStep((value) => Math.min(4, value + 1)) }

  if (definitions.isLoading || policies.isLoading) return <><PageHeader title="Create strategy" description="Configure a strategy through a safe, schema-driven workflow." /><Skeleton lines={7} height={480} /></>
  if (definitions.isError) return <ErrorState title="Strategy definitions are unavailable" error={definitions.error} onRetry={() => void definitions.refetch()} />

  return <div className="page-stack create-strategy-page">
    <PageHeader eyebrow="Strategies / New" title="Create a strategy" description={`Build for ${portfolio?.name || 'the selected portfolio'}. New instances default to SHADOW and are never offered LIVE mode.`} actions={<Link className="button-secondary" to="/strategies"><ArrowLeft />Back to strategies</Link>} />
    <ol className="wizard-steps" aria-label="Create strategy progress">{steps.map((label, index) => <li key={label} className={index === step ? 'active' : index < step ? 'complete' : ''}><span>{index < step ? <Check /> : index + 1}</span><strong>{label}</strong></li>)}</ol>
    <Panel className="wizard-panel">
      {step === 0 && <div className="wizard-content"><div className="wizard-heading"><span>1</span><div><h2>Choose the instrument</h2><p>Search IBKR by ticker or company name, then select and qualify the exact broker contract.</p></div></div><BrokerInstrumentSearch value={draft.ticker} suggestions={instruments.data || []} autoFocus onValueChange={(ticker) => setDraft((current) => ({...current, ticker}))} onContractSelected={(contract) => setDraft((current) => ({...current, exchange: contract.exchange}))} onResolved={(value) => {setResolution(value); setValidation(null)}} /></div>}
      {step === 1 && <WizardDefinition draft={draft} setDraft={setDraft} definitions={definitions.data || []} definition={definition} onDefinition={selectDefinition} />}
      {step === 2 && <WizardParameters draft={draft} setDraft={setDraft} definition={definition} />}
      {step === 3 && <WizardExecution draft={draft} setDraft={setDraft} policies={policies.data} />}
      {step === 4 && <WizardReview draft={draft} definition={definition} resolution={resolution} portfolioName={portfolio?.name} />}
      {(validation || create.isError) && <ErrorState title={validation ? 'Complete this step' : 'Strategy validation failed'} error={validation ? new Error(validation) : create.error} compact />}
      <div className="wizard-footer"><button className="button-secondary" disabled={step === 0 || create.isPending} onClick={() => {setValidation(null); setStep((value) => Math.max(0, value - 1))}}><ArrowLeft />Back</button><span>Step {step + 1} of {steps.length}</span>{step < 4 ? <button className="button-primary" onClick={next}>Continue<ArrowRight /></button> : <button className="button-primary" disabled={create.isPending || !selectedPortfolioId} onClick={() => {if (validateStep()) create.mutate()}}><ShieldCheck />{create.isPending ? 'Validating…' : 'Validate & create'}</button>}</div>
    </Panel>
  </div>
}

function WizardDefinition({draft, setDraft, definitions, definition, onDefinition}: {draft: Draft; setDraft: React.Dispatch<React.SetStateAction<Draft>>; definitions: StrategyDefinition[]; definition: StrategyDefinition | null; onDefinition: (key: string) => void}) {
  return <div className="wizard-content"><div className="wizard-heading"><span>2</span><div><h2>Select a strategy definition</h2><p>Definitions and allowed timeframes come directly from the Backend plugin catalog.</p></div></div><div className="form-grid two-columns"><label>Instance name<input aria-label="Instance name" value={draft.name} placeholder="A descriptive portfolio-unique name" onChange={(event) => setDraft((current) => ({...current, name: event.target.value}))} /></label><label>Definition<select aria-label="Strategy definition" value={draft.definitionKey} onChange={(event) => onDefinition(event.target.value)}><option value="">Choose a backend definition</option>{definitions.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label><label>Timeframe<select aria-label="Timeframe" value={draft.timeframe} disabled={!definition} onChange={(event) => setDraft((current) => ({...current, timeframe: event.target.value}))}><option value="">Choose a timeframe</option>{(definition?.supported_timeframes || []).map((value) => <option key={value}>{value}</option>)}</select></label></div>{definition && <div className="definition-card"><CircleCheck /><div><strong>{definition.name}</strong><p>{definition.description}</p><div>{definition.supported_directions.map((direction) => <StatusBadge key={direction} status={direction} />)}</div></div></div>}</div>
}

function WizardParameters({draft, setDraft, definition}: {draft: Draft; setDraft: React.Dispatch<React.SetStateAction<Draft>>; definition: StrategyDefinition | null}) {
  return <div className="wizard-content"><div className="wizard-heading"><span>3</span><div><h2>Configure parameters</h2><p>Fields, defaults, ranges, and choices are generated from this definition’s parameter schema.</p></div></div>{definition ? <SchemaParameterForm schema={definition.parameter_schema} values={draft.parameters} onChange={(parameters) => setDraft((current) => ({...current, parameters}))} /> : <p>Select a definition first.</p>}</div>
}

function WizardExecution({draft, setDraft, policies}: {draft: Draft; setDraft: React.Dispatch<React.SetStateAction<Draft>>; policies?: {risk_policies: {id: number; name: string}[]; order_policies: {id: number; name: string}[]}}) {
  return <div className="wizard-content"><div className="wizard-heading"><span>4</span><div><h2>Set capital, risk, and execution</h2><p>SHADOW records the complete planning trace without creating an executable OMS order.</p></div></div><div className="form-grid three-columns"><label>Target weight<input aria-label="Target weight" type="number" min="-1" max="1" step="0.0001" value={draft.targetWeight} onChange={(event) => setDraft((current) => ({...current, targetWeight: event.target.value}))} /></label><label>Capital share<input aria-label="Capital share" type="number" min="0" max="1" step="0.01" value={draft.capitalShare} onChange={(event) => setDraft((current) => ({...current, capitalShare: event.target.value}))} /></label><label>Priority<input aria-label="Priority" type="number" min="1" step="1" value={draft.priority} onChange={(event) => setDraft((current) => ({...current, priority: event.target.value}))} /></label><label>Execution mode<select aria-label="Execution mode" value={draft.executionMode} onChange={(event) => setDraft((current) => ({...current, executionMode: event.target.value as Draft['executionMode']}))}><option>SHADOW</option><option>OBSERVE</option><option>PAPER</option></select><small>LIVE is unavailable.</small></label></div><CollapsibleSection title="Advanced policy settings" description="Use platform defaults unless this strategy needs an approved policy override."><div className="form-grid two-columns"><label>Risk policy<select aria-label="Risk policy" value={draft.riskPolicyId} onChange={(event) => setDraft((current) => ({...current, riskPolicyId: event.target.value}))}><option value="">Platform default</option>{(policies?.risk_policies || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label>Order policy<select aria-label="Order policy" value={draft.orderPolicyId} onChange={(event) => setDraft((current) => ({...current, orderPolicyId: event.target.value}))}><option value="">Platform default</option>{(policies?.order_policies || []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label></div></CollapsibleSection></div>
}

function WizardReview({draft, definition, resolution, portfolioName}: {draft: Draft; definition: StrategyDefinition | null; resolution: InstrumentResolution | null; portfolioName?: string}) {
  const review = [
    ['Portfolio', portfolioName || 'Selected portfolio'], ['Instrument', `${draft.ticker.toUpperCase()} · ${draft.exchange}`], ['Contract', resolution?.conid ? `Qualified · conId ${resolution.conid}` : 'Pending / requested on create'],
    ['Definition', definition?.name || '—'], ['Timeframe', draft.timeframe], ['Execution mode', draft.executionMode], ['Target weight', draft.targetWeight], ['Capital share', draft.capitalShare], ['Priority', draft.priority],
  ]
  return <div className="wizard-content"><div className="wizard-heading"><span>5</span><div><h2>Review and validate</h2><p>The Backend performs final schema, contract, mode, and policy validation before creating immutable version 1.</p></div></div><div className="review-grid">{review.map(([label, value]) => <div key={label}><span>{label}</span>{label === 'Execution mode' ? <StatusBadge status={value} /> : <strong>{value}</strong>}</div>)}</div><div className="review-parameters"><h3>Parameters</h3>{Object.entries(draft.parameters).map(([key, value]) => <div key={key}><span>{key.replaceAll('_', ' ')}</span><code>{formatCompact(value)}</code></div>)}</div><div className="safety-path"><ShieldCheck /><div><strong>Execution boundary preserved</strong><p>This strategy can only produce signals and targets. PAPER execution still passes through allocation, sizing, risk, OMS, Gateway, ledger, and reconciliation.</p></div></div></div>
}
