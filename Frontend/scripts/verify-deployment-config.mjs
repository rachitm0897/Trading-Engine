import {readFileSync} from 'node:fs'

const dockerfile = readFileSync('Dockerfile', 'utf8')
const nginx = readFileSync('nginx.conf.template', 'utf8')
const entrypoint = readFileSync('docker-entrypoint.d/40-runtime-config.sh', 'utf8')
const environmentExample = readFileSync('.env.example', 'utf8')
const viteConfig = readFileSync('vite.config.ts', 'utf8')

if (dockerfile.includes('COPY .env.example') || dockerfile.includes('COPY .env ')) {
  throw new Error('Frontend image must not contain an environment file')
}
if (dockerfile.includes('http://backend:8000') || environmentExample.includes('http://backend:8000')) {
  throw new Error('Frontend production configuration uses Docker DNS')
}
if (!nginx.includes('location = /trading_eng_frontend { return 301 /trading_eng_frontend/; }')) {
  throw new Error('Exact Frontend base-path redirect is missing')
}
if (!nginx.includes('absolute_redirect off;')) {
  throw new Error('Frontend redirects must not expose the container port')
}
if (!nginx.includes('^/trading_eng_frontend/(.*)$') || !nginx.includes('location / { try_files')) {
  throw new Error('Prefix-preserved and prefix-stripped SPA fallbacks are required')
}
if (!nginx.includes('Cache-Control "no-store"')) {
  throw new Error('runtime-config.js must not be cached')
}
if (!entrypoint.includes("^https?://") || !entrypoint.includes('single-line HTTP or HTTPS URL')) {
  throw new Error('Runtime Backend URL validation is missing')
}
if (!environmentExample.includes('BACKEND_API_URL=https://qfsplatform.com/trading_eng_backend/api/v1')) {
  throw new Error('Frontend QFS Backend URL is missing')
}
if (!viteConfig.includes('process.env.VITE_APP_BASE_PATH')) {
  throw new Error('Vite base override does not read the build process environment')
}
if (/PUBLIC_BASE_URL|GATEWAY_SERVICE_TOKEN|IBKR_GATEWAY_IMAGE/.test(environmentExample + dockerfile)) {
  throw new Error('Frontend contains Backend/Gateway deployment variables')
}

console.log('frontend deployment configuration verified')
