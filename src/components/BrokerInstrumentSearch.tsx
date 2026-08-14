import {useEffect, useId, useState} from 'react'
import {useMutation, useQuery} from '@tanstack/react-query'
import {Radar} from 'lucide-react'

import {mutationOptions, request, withQuery} from '../api/client'
import {queries} from '../api/queries'
import type {InstrumentResolution, InstrumentSearchResult} from '../api/types'
import {usePreferencesStore} from '../stores/preferences'
import {ErrorState, StatusBadge} from './ui'

const MINIMUM_QUERY_LENGTH = 2
const SEARCH_DEBOUNCE_MS = 400

export function BrokerInstrumentSearch({value, onValueChange, onContractSelected, onResolved, suggestions = [], autoFocus = false, searchLabel = 'Ticker', portfolioId, gatewaySessionId, allowOptions = false}: {
  value: string
  onValueChange: (value: string) => void
  onContractSelected?: (contract: InstrumentSearchResult) => void
  onResolved: (resolution: InstrumentResolution | null) => void
  suggestions?: {id: number; symbol: string}[]
  autoFocus?: boolean
  searchLabel?: string
  portfolioId?: number | null
  gatewaySessionId?: string | null
  allowOptions?: boolean
}) {
  const [assetClass, setAssetClass] = useState<'STK' | 'OPT'>('STK')
  const [selected, setSelected] = useState<InstrumentSearchResult | null>(null)
  const [resolution, setResolution] = useState<InstrumentResolution | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const globallySelectedSessionId = usePreferencesStore((state) => state.selectedSessionId)
  const sessionId = gatewaySessionId === undefined
    ? globallySelectedSessionId
    : gatewaySessionId
  const sessions = useQuery(queries.brokerSessions())
  const selectedSession = (sessions.data || []).find((item) => item.id === sessionId)
  const sessionReady = Boolean(selectedSession?.connected && selectedSession.commands_enabled)
  const suggestionsId = useId()
  useEffect(() => {
    if (!value) {
      setSelected(null)
      setResolution(null)
    }
  }, [value])
  useEffect(() => {
    const next = value.trim()
    if (next.length < MINIMUM_QUERY_LENGTH) {
      setSearchQuery('')
      return
    }
    const timer = window.setTimeout(() => setSearchQuery(next), SEARCH_DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [value])
  useEffect(() => {
    setSelected(null)
    setResolution(null)
    onResolved(null)
  }, [sessionId])
  const search = useQuery({
    queryKey: ['instrument-search', sessionId, allowOptions ? 'IN' : 'ALL', assetClass, searchQuery],
    queryFn: ({signal}) => request<InstrumentSearchResult[]>(
      withQuery('instruments/search/', {
        query: searchQuery,
        session_id: sessionId,
        portfolio_id: portfolioId,
        asset_classes: assetClass,
        country: allowOptions ? 'IN' : undefined,
        currency: allowOptions ? 'INR' : undefined,
      }),
      {signal},
    ),
    enabled: sessionReady && searchQuery.length >= MINIMUM_QUERY_LENGTH,
    staleTime: 60_000,
  })
  const resolve = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error('Select an exact IBKR contract first.')
      return request<InstrumentResolution>('instruments/resolve/', mutationOptions('POST', {
        ...selected, ticker: selected.symbol, qualify: true, session_id: sessionId,
        portfolio_id: portfolioId,
      }, true))
    },
    onSuccess: (data) => {setResolution(data); onResolved(data)},
  })
  const updateValue = (next: string) => {
    setSelected(null)
    setResolution(null)
    onResolved(null)
    onValueChange(next.toUpperCase())
  }
  const changeAssetClass = (next: 'STK' | 'OPT') => {
    setAssetClass(next)
    setSelected(null)
    setResolution(null)
    setSearchQuery('')
    onResolved(null)
    onValueChange('')
  }
  const select = (contract: InstrumentSearchResult) => {
    setSelected(contract)
    setResolution(null)
    onResolved(null)
    onValueChange(contract.symbol)
    onContractSelected?.(contract)
  }
  return <div className="broker-instrument-search">
    {allowOptions && <div className="instrument-type-switch" role="group" aria-label="Instrument type"><button type="button" className={assetClass === 'STK' ? 'selected' : ''} aria-pressed={assetClass === 'STK'} onClick={() => changeAssetClass('STK')}>Stocks</button><button type="button" className={assetClass === 'OPT' ? 'selected' : ''} aria-pressed={assetClass === 'OPT'} onClick={() => changeAssetClass('OPT')}>Options</button></div>}
    <label>IBKR {allowOptions ? `Indian ${assetClass === 'OPT' ? 'option' : 'stock'}` : 'instrument'} search<input aria-label={searchLabel} value={value} list={suggestionsId} placeholder={assetClass === 'OPT' ? 'Underlying or option symbol' : 'Ticker or company name'} onChange={(event) => updateValue(event.target.value)} autoFocus={autoFocus} /><datalist id={suggestionsId}>{suggestions.map((item) => <option key={item.id} value={item.symbol} />)}</datalist></label>
    <div className="contract-search-results" aria-live="polite">
      {!sessionId && <p>Select a connected broker session before searching.</p>}
      {sessionId && !sessionReady && <p>The selected broker session is not connected or command-ready.</p>}
      {sessionReady && value.trim().length > 0 && value.trim().length < MINIMUM_QUERY_LENGTH && <p>Enter at least {MINIMUM_QUERY_LENGTH} characters.</p>}
      {search.isFetching && <p>Searching IBKR contracts...</p>}
      {!search.isFetching && search.isSuccess && searchQuery === value.trim() && !search.data?.length && <p>No matching IBKR contracts.</p>}
      {(search.data || []).map((contract) => <button type="button" className={selected?.conid === contract.conid ? 'selected' : ''} key={contract.conid} aria-label={`Select ${contract.symbol} ${contract.primary_exchange || contract.exchange} ${contract.currency}`} onClick={() => select(contract)}><span><strong>{contract.symbol}</strong><small>{contract.description || contract.local_symbol}</small></span><span><code>{contract.local_symbol}</code><small>{contract.asset_class} / {contract.exchange} / {contract.primary_exchange || 'No primary'} / {contract.currency}</small>{contract.asset_class === 'OPT' && <small>{contract.expiration} · {contract.strike} · {contract.right === 'C' ? 'Call' : 'Put'} · lot {contract.multiplier}</small>}</span><code>conId {contract.conid}</code></button>)}
    </div>
    <div className="contract-card"><div><Radar /><div><strong>Exact IBKR contract qualification</strong><p>{resolution?.conid ? `${resolution.symbol} conId ${resolution.conid} qualified on ${resolution.primary_exchange || resolution.exchange}.` : selected ? `${selected.symbol} on ${selected.primary_exchange || selected.exchange} is selected and ready to qualify.` : 'Select one search result. Ambiguous matches are never chosen automatically.'}</p></div></div><StatusBadge status={resolution?.conid ? 'QUALIFIED' : selected ? 'SELECTED' : 'NOT SELECTED'} /><button type="button" className="button-secondary" disabled={resolve.isPending || !selected || !sessionReady} onClick={() => resolve.mutate()}>{resolve.isPending ? 'Qualifying...' : 'Qualify selected contract'}</button>{selected && <code>conId {selected.conid}</code>}</div>
    {(search.isError || resolve.isError) && <ErrorState title={search.isError ? 'Instrument search failed' : 'Contract qualification failed'} error={search.error || resolve.error} compact />}
  </div>
}
