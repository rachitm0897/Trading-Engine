import {QueryClientProvider} from '@tanstack/react-query'
import {BrowserRouter} from 'react-router-dom'
import {queryClient} from './queryClient'
import {AppRoutes} from '../routes/AppRoutes'

export function appBasename() {
  const configured = import.meta.env.VITE_APP_BASE_PATH || import.meta.env.BASE_URL || '/'
  const normalized = configured.startsWith('/') ? configured : `/${configured}`
  return normalized === '/' ? '/' : normalized.replace(/\/$/, '')
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter basename={appBasename()}>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}

