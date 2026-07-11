import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
export default defineConfig(({mode})=>{const env=loadEnv(mode,process.cwd(),''); const base=(env.VITE_APP_BASE_PATH||'/').replace(/\/?$/,'/'); return {base,plugins:[react()],test:{environment:'jsdom',globals:true,setupFiles:'./tests/setup.ts'}}})
