export type Envelope<T>={ok:boolean;data:T|null;error:{code:string;message:string;details:unknown}|null;meta:Record<string,unknown>}
const configured=import.meta.env.VITE_API_BASE_URL||'/api/v1'
export const API_BASE_URL=configured.replace(/\/$/,'')
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
  const response=await fetch(`${API_BASE_URL}/${path.replace(/^\//,'')}`,{headers:{'Content-Type':'application/json',...(options.headers||{})},...options})
  const body=await response.json() as Envelope<T>
  if(!response.ok||!body.ok) throw new Error(body.error?.message||`Request failed (${response.status})`)
  return body.data as T
}

