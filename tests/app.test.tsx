import {render,screen,waitFor} from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../src/App'

const data:Record<string,any>={system:{mode:'PAPER',material_breaks:0},gateway:{connected:true,reconciled:true,mode:'paper'},accounts:[],instruments:[{id:1,symbol:'AAPL',exchange:'SMART'}],portfolios:[{id:1,name:'Paper'}],positions:[],orders:[],executions:[],strategies:[{id:1,name:'SMA',strategy_type:'sma_trend',version:1,enabled:true}],risk:{kill_switches:[],decisions:[]},reconciliation:{runs:[],breaks:[]},streaming:{kafka_enabled:true,metrics:[],flink:{jobs:[]}},allocations:[],rebalancing:[],audit:[]}
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
