import {useEffect, useMemo, useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {ArrowLeft, ArrowRight, Check, CircleCheck, Radar, ShieldCheck} from 'lucide-react'
import {Link, useNavigate} from 'react-router-dom'
import {mutationOptions, request, withQuery} from '../../api/client'
import {queries} from '../../api/queries'
import type {InstrumentResolution, InstrumentSearchResult, ParameterProperty, Scalar, StrategyDefinition, StrategyInstance} from '../../api/types'
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

function fieldValue(value: Scalar | undefined) {
  return value === null || value === undefined ? '' : String(value)
}

function parseParameter(value: string, schema: ParameterProperty): Scalar {
  if (schema.type === 'integer' || schema.type === 'number') return value === '' ? null : Number(value)
  if (schema.type === 'boolean') return value === 'true'
  return value
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
  const [selectedContract, setSelectedContract] = useState<InstrumentSearchResult | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const definition = definitions.data?.find((item) => item.key === draft.definitionKey) || null
  const exchanges = useMemo(() => [...new Set(['SMART', ...(instruments.data || []).map((item) => item.exchange).filter(Boolean)])], [instruments.data])

  useEffect(() => {
    const timer=window.setTimeout(() => setSearchQuery(draft.ticker.trim()), 350)
    return () => window.clearTimeout(timer)
  }, [draft.ticker])
  const contractSearch=useQuery({
    queryKey: ['instrument-search', searchQuery],
    queryFn: () => request<InstrumentSearchResult[]>(withQuery('instruments/search/', {query: searchQuery})),
    enabled: searchQuery.length > 0,
    staleTime: 60_000,
  })

  const resolveContract = useMutation({
    mutationFn: () => {
      if (!selectedContract) throw new Error('Select an exact IBKR contract first.')
      return request<InstrumentResolution>('instruments/resolve/', mutationOptions('POST', {...selectedContract, ticker: selectedContract.symbol, qualify: true}, true))
    },
    onSuccess: (data) => {setResolution(data); setValidation(null)},
  })
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
    else if (step === 0 && !selectedContract) error = 'Select an exact IBKR contract before continuing.'
    else if (step === 0 && selectedContract && (!resolution?.conid || resolution.conid !== selectedContract.conid)) error = 'Qualify the selected IBKR contract before continuing.'
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
      {step === 0 && <BrokerInstrumentSearch draft={draft} setDraft={setDraft} instruments={instruments.data || []} exchanges={exchanges}
        results={contractSearch.data || []} searching={contractSearch.isFetching} selected={selectedContract} resolution={resolution}
        resolving={resolveContract.isPending} onTicker={(ticker) => {setSelectedContract(null);setResolution(null);setDraft((current) => ({...current,ticker:ticker.toUpperCase()}))}}
        onSelect={(contract) => {setSelectedContract(contract);setResolution(null);setDraft((current) => ({...current,ticker:contract.symbol,exchange:contract.exchange}))}}
        onResolve={() => {if (selectedContract) resolveContract.mutate(); else setValidation('Select an exact IBKR contract before qualification.')}} />}
      {step === 1 && <WizardDefinition draft={draft} setDraft={setDraft} definitions={definitions.data || []} definition={definition} onDefinition={selectDefinition} />}
      {step === 2 && <WizardParameters draft={draft} setDraft={setDraft} definition={definition} />}
      {step === 3 && <WizardExecution draft={draft} setDraft={setDraft} policies={policies.data} />}
      {step === 4 && <WizardReview draft={draft} definition={definition} resolution={resolution} portfolioName={portfolio?.name} />}
      {(validation || contractSearch.isError || resolveContract.isError || create.isError) && <ErrorState title={validation ? 'Complete this step' : create.isError ? 'Strategy validation failed' : contractSearch.isError ? 'Instrument search failed' : 'Contract check failed'} error={validation ? new Error(validation) : create.error || contractSearch.error || resolveContract.error} compact />}
      <div className="wizard-footer"><button className="button-secondary" disabled={step === 0 || create.isPending} onClick={() => {setValidation(null); setStep((value) => Math.max(0, value - 1))}}><ArrowLeft />Back</button><span>Step {step + 1} of {steps.length}</span>{step < 4 ? <button className="button-primary" onClick={next}>Continue<ArrowRight /></button> : <button className="button-primary" disabled={create.isPending || !selectedPortfolioId} onClick={() => {if (validateStep()) create.mutate()}}><ShieldCheck />{create.isPending ? 'Validating…' : 'Validate & create'}</button>}</div>
    </Panel>
  </div>
}

function BrokerInstrumentSearch({draft, setDraft, instruments, exchanges, results, searching, selected, resolution, resolving, onTicker, onSelect, onResolve}: {draft: Draft; setDraft: React.Dispatch<React.SetStateAction<Draft>>; instruments: {id: number; symbol: string}[]; exchanges: string[]; results: InstrumentSearchResult[]; searching: boolean; selected: InstrumentSearchResult | null; resolution: InstrumentResolution | null; resolving: boolean; onTicker: (ticker: string) => void; onSelect: (contract: InstrumentSearchResult) => void; onResolve: () => void}) {
  return <div className="wizard-content"><div className="wizard-heading"><span>1</span><div><h2>Choose the instrument</h2><p>Search IBKR by ticker or company name, then select the exact broker contract.</p></div></div><div className="form-grid two-columns"><label>IBKR instrument search<input aria-label="Ticker" value={draft.ticker} list="instrument-symbols" placeholder="Ticker or company name" onChange={(event) => onTicker(event.target.value)} autoFocus /><datalist id="instrument-symbols">{instruments.map((item) => <option key={item.id} value={item.symbol} />)}</datalist></label><label>Routing exchange<select aria-label="Exchange" value={draft.exchange} disabled={Boolean(selected)} onChange={(event) => setDraft((current) => ({...current, exchange: event.target.value}))}>{exchanges.map((exchange) => <option key={exchange}>{exchange}</option>)}</select></label></div>
    <div className="contract-search-results" aria-live="polite">{searching && <p>Searching IBKR contracts...</p>}{!searching && draft.ticker && !results.length && <p>No matching IBKR contracts.</p>}{results.map((contract) => <button type="button" className={selected?.conid===contract.conid?'selected':''} key={contract.conid} aria-label={`Select ${contract.symbol} ${contract.primary_exchange || contract.exchange} ${contract.currency}`} onClick={() => onSelect(contract)}><span><strong>{contract.symbol}</strong><small>{contract.description || contract.local_symbol}</small></span><span><code>{contract.local_symbol}</code><small>{contract.asset_class} / {contract.exchange} / {contract.primary_exchange || 'No primary'} / {contract.currency}</small></span><code>conId {contract.conid}</code></button>)}</div>
    <div className="contract-card"><div><Radar /><div><strong>Exact IBKR contract qualification</strong><p>{resolution?.conid ? `${resolution.symbol} conId ${resolution.conid} qualified on ${resolution.primary_exchange || resolution.exchange}.` : selected ? `${selected.symbol} on ${selected.primary_exchange || selected.exchange} is selected and ready to qualify.` : 'Select one search result. Ambiguous matches are never chosen automatically.'}</p></div></div><StatusBadge status={resolution?.conid ? 'QUALIFIED' : selected ? 'SELECTED' : 'NOT SELECTED'} /><button className="button-secondary" disabled={resolving || !selected} onClick={onResolve}>{resolving ? 'Qualifying...' : 'Qualify selected contract'}</button>{selected && <code>conId {selected.conid}</code>}</div></div>
}

function WizardInstrument({draft, setDraft, instruments, exchanges, resolution, resolving, onResolve}: {draft: Draft; setDraft: React.Dispatch<React.SetStateAction<Draft>>; instruments: {id: number; symbol: string}[]; exchanges: string[]; resolution: InstrumentResolution | null; resolving: boolean; onResolve: () => void}) {
  return <div className="wizard-content"><div className="wizard-heading"><span>1</span><div><h2>Choose the instrument</h2><p>Enter any ticker supported by your broker permissions. Existing instruments are suggestions, not a fixed universe.</p></div></div><div className="form-grid two-columns"><label>Ticker<input aria-label="Ticker" value={draft.ticker} list="instrument-symbols" placeholder="Enter a ticker" onChange={(event) => setDraft((current) => ({...current, ticker: event.target.value.toUpperCase()}))} autoFocus /><datalist id="instrument-symbols">{instruments.map((item) => <option key={item.id} value={item.symbol} />)}</datalist></label><label>Exchange<select aria-label="Exchange" value={draft.exchange} onChange={(event) => setDraft((current) => ({...current, exchange: event.target.value}))}>{exchanges.map((exchange) => <option key={exchange}>{exchange}</option>)}</select></label></div><div className="contract-card"><div><Radar /><div><strong>IBKR contract qualification</strong><p>{resolution ? resolution.conid ? `${resolution.symbol} qualified on ${resolution.primary_exchange || resolution.exchange}.` : 'Qualification was requested and remains pending.' : 'Check the canonical contract before creation, or let creation request qualification.'}</p></div></div><StatusBadge status={resolution?.conid ? 'QUALIFIED' : resolution ? 'PENDING' : 'NOT CHECKED'} /><button className="button-secondary" disabled={resolving} onClick={onResolve}>{resolving ? 'Checking…' : 'Check contract'}</button>{resolution?.conid && <code>conId {resolution.conid}</code>}</div></div>
}

function WizardDefinition({draft, setDraft, definitions, definition, onDefinition}: {draft: Draft; setDraft: React.Dispatch<React.SetStateAction<Draft>>; definitions: StrategyDefinition[]; definition: StrategyDefinition | null; onDefinition: (key: string) => void}) {
  return <div className="wizard-content"><div className="wizard-heading"><span>2</span><div><h2>Select a strategy definition</h2><p>Definitions and allowed timeframes come directly from the Backend plugin catalog.</p></div></div><div className="form-grid two-columns"><label>Instance name<input aria-label="Instance name" value={draft.name} placeholder="A descriptive portfolio-unique name" onChange={(event) => setDraft((current) => ({...current, name: event.target.value}))} /></label><label>Definition<select aria-label="Strategy definition" value={draft.definitionKey} onChange={(event) => onDefinition(event.target.value)}><option value="">Choose a backend definition</option>{definitions.map((item) => <option key={item.key} value={item.key}>{item.name}</option>)}</select></label><label>Timeframe<select aria-label="Timeframe" value={draft.timeframe} disabled={!definition} onChange={(event) => setDraft((current) => ({...current, timeframe: event.target.value}))}><option value="">Choose a timeframe</option>{(definition?.supported_timeframes || []).map((value) => <option key={value}>{value}</option>)}</select></label></div>{definition && <div className="definition-card"><CircleCheck /><div><strong>{definition.name}</strong><p>{definition.description}</p><div>{definition.supported_directions.map((direction) => <StatusBadge key={direction} status={direction} />)}</div></div></div>}</div>
}

function WizardParameters({draft, setDraft, definition}: {draft: Draft; setDraft: React.Dispatch<React.SetStateAction<Draft>>; definition: StrategyDefinition | null}) {
  const properties = Object.entries(definition?.parameter_schema.properties || {})
  return <div className="wizard-content"><div className="wizard-heading"><span>3</span><div><h2>Configure parameters</h2><p>Fields, defaults, ranges, and choices are generated from this definition’s parameter schema.</p></div></div>{definition ? <div className="form-grid two-columns">{properties.map(([key, schema]) => <label key={key}>{schema.title || key.replaceAll('_', ' ')}{schema.description && <small>{schema.description}</small>}{schema.enum ? <select aria-label={key.replaceAll('_', ' ')} value={fieldValue(draft.parameters[key])} onChange={(event) => setDraft((current) => ({...current, parameters: {...current.parameters, [key]: parseParameter(event.target.value, schema)}}))}>{schema.enum.map((value) => <option key={String(value)} value={String(value)}>{String(value)}</option>)}</select> : schema.type === 'boolean' ? <select aria-label={key.replaceAll('_', ' ')} value={fieldValue(draft.parameters[key])} onChange={(event) => setDraft((current) => ({...current, parameters: {...current.parameters, [key]: event.target.value === 'true'}}))}><option value="true">Yes</option><option value="false">No</option></select> : <input aria-label={key.replaceAll('_', ' ')} type={schema.type === 'integer' || schema.type === 'number' ? 'number' : 'text'} step={schema.type === 'integer' ? 1 : 'any'} min={schema.minimum ?? schema.exclusiveMinimum} max={schema.maximum ?? schema.exclusiveMaximum} value={fieldValue(draft.parameters[key])} onChange={(event) => setDraft((current) => ({...current, parameters: {...current.parameters, [key]: parseParameter(event.target.value, schema)}}))} />}</label>)}</div> : <p>Select a definition first.</p>}</div>
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
