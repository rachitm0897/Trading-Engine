import {render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../src/App'

const data:Record<string,any>={system:{mode:'PAPER',material_breaks:0},gateway:{connected:true,reconciled:true,mode:'paper'},accounts:[],instruments:[{id:1,symbol:'AAPL',exchange:'SMART'}],portfolios:[{id:1,name:'Paper'}],positions:[],orders:[],executions:[],strategies:[{id:1,name:'SMA',strategy_type:'sma_trend',version:1,enabled:true}],
 'strategy-definitions':[{key:'RSI_MEAN_REVERSION',name:'RSI Mean Reversion',supported_timeframes:['1m','5m'],default_parameters:{window:14,entry_threshold:30,exit_threshold:65,direction:'LONG'},input_requirements:[{name:'rsi',parameters:{window:14},warmup_bars:15}],parameter_schema:{properties:{window:{type:'integer',minimum:2},entry_threshold:{type:'number'},exit_threshold:{type:'number'},direction:{enum:['LONG','SHORT','BOTH']}}}}],
 'strategy-instances':[],'strategy-policies':{risk_policies:[],order_policies:[]},risk:{kill_switches:[],decisions:[]},reconciliation:{runs:[],breaks:[]},streaming:{kafka_enabled:true,metrics:[],flink:{jobs:[]}},allocations:[],rebalancing:[],audit:[]}
beforeEach(()=>{vi.stubGlobal('fetch',vi.fn(async(input:string,init?:RequestInit)=>{const key=Object.keys(data).find(x=>input.includes(`/${x}/`))||'system';return {ok:true,json:async()=>({ok:true,data:init?.method==='POST'?{}:data[key],error:null,meta:{}})} as Response}))})
afterEach(()=>vi.unstubAllGlobals())

test('renders terminal workflow pages and paper status',async()=>{
 render(<App/>); await waitFor(()=>expect(screen.getAllByText('PAPER').length).toBeGreaterThan(0))
 for(const name of ['Overview','Gateway','Accounts','Portfolio','Strategies','Streaming','Allocations','Rebalancing','Orders','Executions','Reconciliation','Risk','System Logs']) expect(screen.getByRole('button',{name:new RegExp(name)})).toBeInTheDocument()
})

test('routes between screens and validates an order',async()=>{
 const user=userEvent.setup();render(<App/>);await user.click(screen.getByRole('button',{name:/Orders/}));
 await user.type(screen.getByLabelText('QUANTITY'),'10');await user.type(screen.getByLabelText('REFERENCE PRICE'),'100');await user.click(screen.getByRole('button',{name:'SUBMIT TO RISK'}));
 await waitFor(()=>expect(screen.getByText(/ACCEPTED|VALIDATED/)).toBeInTheDocument())
})

test('shows kill-switch confirmation before action',async()=>{
 const user=userEvent.setup();render(<App/>);await user.click(screen.getByRole('button',{name:/Risk/}));await user.click(screen.getByRole('button',{name:/ENGAGE GLOBAL/}));
 expect(screen.getByText('CONFIRM GLOBAL TRADING HALT')).toBeInTheDocument();expect(screen.getByRole('button',{name:'CONFIRM KILL SWITCH'})).toBeInTheDocument()
})

test('uses configured API base path',async()=>{
 render(<App/>);await waitFor(()=>expect(fetch).toHaveBeenCalled());expect(String((fetch as any).mock.calls[0][0])).toContain('/api/v1/')
})

test('builds configurable strategies in shadow mode without a live option',async()=>{
 const user=userEvent.setup();render(<App/>);await user.click(screen.getByRole('button',{name:/Strategies/}));
 expect(await screen.findByText('STRATEGY BUILDER // SHADOW DEFAULT')).toBeInTheDocument();expect(screen.getByLabelText('TICKER')).toBeInTheDocument()
 const mode=screen.getByLabelText('EXECUTION MODE');expect(mode).toHaveValue('SHADOW');expect(screen.queryByRole('option',{name:'LIVE'})).not.toBeInTheDocument()
})
