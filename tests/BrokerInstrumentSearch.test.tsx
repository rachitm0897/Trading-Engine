import {useState} from 'react'
import {QueryClient, QueryClientProvider} from '@tanstack/react-query'
import {render, screen, waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {BrokerInstrumentSearch} from '../src/components/BrokerInstrumentSearch'
import {usePreferencesStore} from '../src/stores/preferences'


const session = {
  id: 'session-search',
  display_name: 'Connected paper',
  username_hint: 'du-test',
  mode: 'paper',
  status: 'CONNECTED',
  connected: true,
  commands_enabled: true,
  container_status: 'running',
  account_count: 1,
  last_error: '',
  last_gateway_state: {connected: true},
  created_at: '',
  updated_at: '',
  provisioned_at: null,
  connected_at: null,
  last_checked_at: null,
  deleted_at: null,
  needs_novnc: false,
  novnc_url: null,
}

function envelope(data: unknown) {
  return {ok: true, status: 200, json: async () => ({ok: true, data, error: null, meta: {}})} as Response
}

function Harness() {
  const [value,setValue]=useState('')
  return <BrokerInstrumentSearch value={value} onValueChange={setValue} onResolved={() => undefined} />
}

function renderSearch() {
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})
  return render(<QueryClientProvider client={client}><Harness /></QueryClientProvider>)
}

beforeEach(() => {
  usePreferencesStore.setState({
    selectedSessionId: session.id,
    selectedAccountId: null,
    selectedPortfolioId: null,
  })
})

afterEach(() => vi.unstubAllGlobals())


test('requires two characters and debounces IBKR symbol searches', async () => {
  const searchUrls:string[]=[]
  vi.stubGlobal('fetch',vi.fn(async (input:string) => {
    const url=String(input)
    if (url.includes('/broker-sessions/')) return envelope([session])
    if (url.includes('/instruments/search/')) {
      searchUrls.push(url)
      return envelope([{
        symbol:'AP',local_symbol:'AP',conid:42,asset_class:'STK',exchange:'SMART',
        primary_exchange:'NYSE',currency:'USD',description:'Ampco-Pittsburgh',instrument_id:null,
      }])
    }
    return envelope([])
  }))
  const user=userEvent.setup()
  renderSearch()
  const input=screen.getByLabelText('Ticker')

  await user.type(input,'A')
  expect(await screen.findByText('Enter at least 2 characters.')).toBeInTheDocument()
  await new Promise((resolve) => window.setTimeout(resolve,450))
  expect(searchUrls).toHaveLength(0)

  await user.type(input,'P')
  expect(await screen.findByRole('button',{name:'Select AP NYSE USD'})).toBeInTheDocument()
  expect(searchUrls).toHaveLength(1)
  expect(searchUrls[0]).toContain('query=AP')
  expect(searchUrls[0]).toContain(`session_id=${session.id}`)
})


test('aborts a stale frontend search when the ticker changes', async () => {
  let firstSignal:AbortSignal|undefined
  vi.stubGlobal('fetch',vi.fn((input:string,init?:RequestInit) => {
    const url=String(input)
    if (url.includes('/broker-sessions/')) return Promise.resolve(envelope([session]))
    if (url.includes('query=AAP')) return Promise.resolve(envelope([{
      symbol:'AAP',local_symbol:'AAP',conid:43,asset_class:'STK',exchange:'SMART',
      primary_exchange:'NYSE',currency:'USD',description:'Advance Auto Parts',instrument_id:null,
    }]))
    if (url.includes('query=AA&')) {
      firstSignal=init?.signal as AbortSignal|undefined
      return new Promise<Response>((_resolve,reject) => {
        firstSignal?.addEventListener('abort',() => reject(new DOMException('Aborted','AbortError')))
      })
    }
    return Promise.resolve(envelope([]))
  }))
  const user=userEvent.setup()
  renderSearch()
  const input=screen.getByLabelText('Ticker')

  await user.type(input,'AA')
  await waitFor(() => expect(firstSignal).toBeDefined(),{timeout:1500})
  await user.type(input,'P')

  expect(await screen.findByRole('button',{name:'Select AAP NYSE USD'})).toBeInTheDocument()
  await waitFor(() => expect(firstSignal?.aborted).toBe(true))
  expect(screen.queryByRole('button',{name:/Select AA /})).not.toBeInTheDocument()
})
