import { loadEnv } from 'vite'
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

function normalizeBase(value: string) {
  const leading = value.startsWith('/') ? value : `/${value}`
  return `${leading.replace(/\/+$/, '')}/`
}

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, process.cwd(), '')
  const defaultBase = mode === 'production' ? '/trading_eng_frontend/' : '/'
  const configuredBase = process.env.VITE_APP_BASE_PATH || env.VITE_APP_BASE_PATH || defaultBase
  const base = mode === 'test' ? '/' : normalizeBase(configuredBase)
  return {base, plugins: [react()], test: {environment: 'jsdom', globals: true, setupFiles: './tests/setup.ts'}}
})
