import {create} from 'zustand'
import {api} from './api'
type State={gateway:any;system:any;accounts:any[];instruments:any[];portfolios:any[];positions:any[];orders:any[];executions:any[];strategies:any[];risk:any;reconciliation:any;logs:any[];loading:boolean;error:string|null;refresh:()=>Promise<void>}
export const useTerminalStore=create<State>((set)=>({gateway:null,system:null,accounts:[],instruments:[],portfolios:[],positions:[],orders:[],executions:[],strategies:[],risk:{},reconciliation:{runs:[],breaks:[]},logs:[],loading:false,error:null,refresh:async()=>{
 set({loading:true,error:null})
 const endpoints=['system','gateway','accounts','instruments','portfolios','positions','orders','executions','strategies','risk','reconciliation','audit'] as const
 const results=await Promise.allSettled(endpoints.map(x=>api<any>(`${x}/`)))
 const next:any={loading:false}; results.forEach((r,i)=>{if(r.status==='fulfilled')next[endpoints[i]==='audit'?'logs':endpoints[i]]=r.value; else next.error=r.reason.message}); set(next)
}}))
