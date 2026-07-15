import {useQuery, useQueryClient} from '@tanstack/react-query'
import {Activity, BookOpen, Bot, ChevronRight, Gauge, LayoutDashboard, Menu, RefreshCw, ServerCog, Target, X} from 'lucide-react'
import {NavLink, Outlet, useLocation} from 'react-router-dom'
import {queries} from '../api/queries'
import {ErrorState, StatusBadge} from '../components/ui'
import {usePreferencesStore} from '../stores/preferences'
import {useSelection} from '../stores/useSelection'

const navigation = [
  {to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard},
  {to: '/strategies', label: 'Strategies', icon: Bot},
  {to: '/portfolio-builder', label: 'Portfolio Builder', icon: Target},
  {to: '/portfolio', label: 'Portfolio', icon: BookOpen},
  {to: '/activity', label: 'Orders & Activity', icon: Activity},
  {to: '/system', label: 'System', icon: ServerCog},
]

export function AppShell() {
  const location = useLocation()
  const queryClient = useQueryClient()
  const system = useQuery(queries.system())
  const selection = useSelection()
  const navigationOpen = usePreferencesStore((state) => state.navigationOpen)
  const setNavigationOpen = usePreferencesStore((state) => state.setNavigationOpen)
  const page = navigation.find((item) => location.pathname.startsWith(item.to))?.label || 'Trading Engine'

  const selectAccount = (accountId: number) => {
    selection.setSelectedAccount(accountId)
    const nextPortfolio = selection.allPortfolios.find((item) => !item.account_id || item.account_id === accountId)
    selection.setSelectedPortfolio(nextPortfolio?.id ?? null, accountId)
  }

  return (
    <div className="app-shell">
      {navigationOpen && <button className="nav-scrim" aria-label="Close navigation" onClick={() => setNavigationOpen(false)} />}
      <aside className={`sidebar ${navigationOpen ? 'sidebar-open' : ''}`}>
        <div className="brand"><div className="brand-mark"><Gauge /></div><div><strong>Finflock</strong><span>Trading Engine</span></div><button className="icon-button sidebar-close" aria-label="Close navigation" onClick={() => setNavigationOpen(false)}><X /></button></div>
        <nav aria-label="Primary navigation">{navigation.map(({to, label, icon: Icon}) => <NavLink key={to} to={to} onClick={() => setNavigationOpen(false)} className={({isActive}) => isActive ? 'active' : ''}><Icon /><span>{label}</span><ChevronRight /></NavLink>)}</nav>
        <div className="safety-note"><StatusBadge status={system.data?.mode || 'PAPER'} /><p>Paper-first. No direct TWS access.</p></div>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <div className="topbar-title"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setNavigationOpen(true)}><Menu /></button><div><span>Trading Engine</span><strong>{page}</strong></div></div>
          <div className="context-selectors">
            <label><span>Account</span><select aria-label="Selected account" value={selection.selectedAccountId ?? ''} disabled={!selection.accounts.length} onChange={(event) => selectAccount(Number(event.target.value))}><option value="" disabled>No accounts</option>{selection.accounts.map((account) => <option key={account.id} value={account.id}>{account.alias || account.account_id}</option>)}</select></label>
            <label><span>Portfolio</span><select aria-label="Selected portfolio" value={selection.selectedPortfolioId ?? ''} disabled={!selection.portfolios.length} onChange={(event) => {const id = Number(event.target.value); const portfolio = selection.portfolios.find((item) => item.id === id); selection.setSelectedPortfolio(id, portfolio?.account_id)}}><option value="" disabled>No portfolios</option>{selection.portfolios.map((portfolio) => <option key={portfolio.id} value={portfolio.id}>{portfolio.name}</option>)}</select></label>
            <StatusBadge status={system.isError ? 'DEGRADED' : system.data?.mode || 'PAPER'} />
            <button className="icon-button" aria-label="Refresh all data" onClick={() => void queryClient.invalidateQueries()}><RefreshCw className={queryClient.isFetching() ? 'spin' : ''} /></button>
          </div>
        </header>
        {selection.error && <div className="global-error"><ErrorState error={selection.error} compact /></div>}
        <main className="page-content"><Outlet /></main>
      </div>
    </div>
  )
}
