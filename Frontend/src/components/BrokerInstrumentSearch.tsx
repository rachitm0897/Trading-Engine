import {useEffect, useId, useState} from 'react'
import {useMutation, useQuery} from '@tanstack/react-query'
import {Radar} from 'lucide-react'

import {mutationOptions, request, withQuery} from '../api/client'
import type {InstrumentResolution, InstrumentSearchResult} from '../api/types'
import {usePreferencesStore} from '../stores/preferences'
import {ErrorState, StatusBadge} from './ui'


export function BrokerInstrumentSearch({value, onValueChange, onContractSelected, onResolved, suggestions = [], autoFocus = false, searchLabel = 'Ticker'}: {
  value: string
  onValueChange: (value: string) => void
  onContractSelected?: (contract: InstrumentSearchResult) => void
  onResolved: (resolution: InstrumentResolution | null) => void
  suggestions?: {id: number; symbol: string}[]
  autoFocus?: boolean
  searchLabel?: string
}) {
  const [selected, setSelected] = useState<InstrumentSearchResult | null>(null)
  const [resolution, setResolution] = useState<InstrumentResolution | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const sessionId = usePreferencesStore((state) => state.selectedSessionId)
  const suggestionsId = useId()
  useEffect(() => {
    if (!value) {
      setSelected(null)
      setResolution(null)
    }
  }, [value])
  useEffect(() => {
    const timer = window.setTimeout(() => setSearchQuery(value.trim()), 350)
    return () => window.clearTimeout(timer)
  }, [value])
  const search = useQuery({
    queryKey: ['instrument-search', sessionId, searchQuery],
    queryFn: () => request<InstrumentSearchResult[]>(withQuery('instruments/search/', {query: searchQuery, session_id: sessionId})),
    enabled: searchQuery.length > 0,
    staleTime: 60_000,
  })
  const resolve = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error('Select an exact IBKR contract first.')
      return request<InstrumentResolution>('instruments/resolve/', mutationOptions('POST', {
        ...selected, ticker: selected.symbol, qualify: true, session_id: sessionId,
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
  const select = (contract: InstrumentSearchResult) => {
    setSelected(contract)
    setResolution(null)
    onResolved(null)
    onValueChange(contract.symbol)
    onContractSelected?.(contract)
  }
  return <div className="broker-instrument-search">
    <label>IBKR instrument search<input aria-label={searchLabel} value={value} list={suggestionsId} placeholder="Ticker or company name" onChange={(event) => updateValue(event.target.value)} autoFocus={autoFocus} /><datalist id={suggestionsId}>{suggestions.map((item) => <option key={item.id} value={item.symbol} />)}</datalist></label>
    <div className="contract-search-results" aria-live="polite">{search.isFetching && <p>Searching IBKR contracts...</p>}{!search.isFetching && value && !search.data?.length && <p>No matching IBKR contracts.</p>}{(search.data || []).map((contract) => <button type="button" className={selected?.conid === contract.conid ? 'selected' : ''} key={contract.conid} aria-label={`Select ${contract.symbol} ${contract.primary_exchange || contract.exchange} ${contract.currency}`} onClick={() => select(contract)}><span><strong>{contract.symbol}</strong><small>{contract.description || contract.local_symbol}</small></span><span><code>{contract.local_symbol}</code><small>{contract.asset_class} / {contract.exchange} / {contract.primary_exchange || 'No primary'} / {contract.currency}</small></span><code>conId {contract.conid}</code></button>)}</div>
    <div className="contract-card"><div><Radar /><div><strong>Exact IBKR contract qualification</strong><p>{resolution?.conid ? `${resolution.symbol} conId ${resolution.conid} qualified on ${resolution.primary_exchange || resolution.exchange}.` : selected ? `${selected.symbol} on ${selected.primary_exchange || selected.exchange} is selected and ready to qualify.` : 'Select one search result. Ambiguous matches are never chosen automatically.'}</p></div></div><StatusBadge status={resolution?.conid ? 'QUALIFIED' : selected ? 'SELECTED' : 'NOT SELECTED'} /><button type="button" className="button-secondary" disabled={resolve.isPending || !selected} onClick={() => resolve.mutate()}>{resolve.isPending ? 'Qualifying...' : 'Qualify selected contract'}</button>{selected && <code>conId {selected.conid}</code>}</div>
    {(search.isError || resolve.isError) && <ErrorState title={search.isError ? 'Instrument search failed' : 'Contract qualification failed'} error={search.error || resolve.error} compact />}
  </div>
}
