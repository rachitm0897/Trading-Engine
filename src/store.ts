import {create} from 'zustand'
import {api} from './api'
type State={gateway:any;system:any;accounts:any[];instruments:any[];portfolios:any[];positions:any[];orders:any[];executions:any[];strategies:any[];strategyDefinitions:any[];strategyInstances:any[];strategyPolicies:any;risk:any;reconciliation:any;streaming:any;allocationPolicies:any[];allocationRuns:any[];rebalancePolicies:any[];rebalanceRuns:any[];logs:any[];loading:boolean;error:string|null;refresh:()=>Promise<void>}
export const useTerminalStore=create<State>((set)=>({gateway:null,system:null,accounts:[],instruments:[],portfolios:[],positions:[],orders:[],executions:[],strategies:[],strategyDefinitions:[],strategyInstances:[],strategyPolicies:{risk_policies:[],order_policies:[]},risk:{},reconciliation:{runs:[],breaks:[]},streaming:{},allocationPolicies:[],allocationRuns:[],rebalancePolicies:[],rebalanceRuns:[],logs:[],loading:false,error:null,refresh:async()=>{
 set({loading:true,error:null})
 const endpoints=['system','gateway','accounts','instruments','portfolios','positions','orders','executions','strategies','strategy-definitions','strategy-instances','strategy-policies','risk','reconciliation','streaming/health','allocations/policies','allocations/runs','rebalancing/policies','rebalancing/runs','audit'] as const
 const results=await Promise.allSettled(endpoints.map(x=>api<any>(`${x}/`)))
 const names=['system','gateway','accounts','instruments','portfolios','positions','orders','executions','strategies','strategyDefinitions','strategyInstances','strategyPolicies','risk','reconciliation','streaming','allocationPolicies','allocationRuns','rebalancePolicies','rebalanceRuns','logs']
 const next:any={loading:false}; results.forEach((r,i)=>{if(r.status==='fulfilled')next[names[i]]=r.value; else next.error=r.reason.message}); set(next)
}}))
