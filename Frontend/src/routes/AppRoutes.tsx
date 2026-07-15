import {Navigate, Route, Routes} from 'react-router-dom'
import {DashboardPage} from '../features/dashboard/DashboardPage'
import {OrdersActivityPage} from '../features/orders/OrdersActivityPage'
import {PortfolioPage} from '../features/portfolio/PortfolioPage'
import {PortfolioBuilderPage} from '../features/portfolio-builder/PortfolioBuilderPage'
import {CreateStrategyPage} from '../features/strategies/CreateStrategyPage'
import {StrategiesPage} from '../features/strategies/StrategiesPage'
import {StrategyDetailPage} from '../features/strategies/StrategyDetailPage'
import {SystemPage} from '../features/system/SystemPage'
import {AppShell} from '../layouts/AppShell'
import {NotFoundPage} from './NotFoundPage'

export function AppRoutes() {
  return <Routes><Route element={<AppShell />}><Route index element={<Navigate to="/dashboard" replace />} /><Route path="dashboard" element={<DashboardPage />} /><Route path="strategies" element={<StrategiesPage />} /><Route path="strategies/new" element={<CreateStrategyPage />} /><Route path="strategies/:strategyId" element={<StrategyDetailPage />} /><Route path="portfolio-builder" element={<PortfolioBuilderPage />} /><Route path="portfolio" element={<PortfolioPage />} /><Route path="activity" element={<OrdersActivityPage />} /><Route path="system" element={<SystemPage />} /><Route path="*" element={<NotFoundPage />} /></Route></Routes>
}
