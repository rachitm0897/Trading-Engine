import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig(({mode})=>{const env=loadEnv(mode,process.cwd(),''); const defaultBase=mode==='production'?'/trading_eng_frontend/':'/'; const base=(mode==='test'?'/':env.VITE_APP_BASE_PATH||defaultBase).replace(/\/?$/,'/'); return {base,plugins:[react()],test:{environment:'jsdom',globals:true,setupFiles:'./tests/setup.ts'}}})
