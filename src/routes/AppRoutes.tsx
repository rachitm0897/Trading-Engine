import {lazy, Suspense} from 'react'
import {Navigate, Route, Routes} from 'react-router-dom'
import {Skeleton} from '../components/ui'
import {AppShell} from '../layouts/AppShell'
import {NotFoundPage} from './NotFoundPage'

const DashboardPage = lazy(() => import('../features/dashboard/DashboardPage').then((module) => ({default: module.DashboardPage})))
const OrdersActivityPage = lazy(() => import('../features/orders/OrdersActivityPage').then((module) => ({default: module.OrdersActivityPage})))
const PortfolioPage = lazy(() => import('../features/portfolio/PortfolioPage').then((module) => ({default: module.PortfolioPage})))
const PortfolioBuilderPage = lazy(() => import('../features/portfolio-builder/PortfolioBuilderPage').then((module) => ({default: module.PortfolioBuilderPage})))
const CreateStrategyPage = lazy(() => import('../features/strategies/CreateStrategyPage').then((module) => ({default: module.CreateStrategyPage})))
const StrategiesPage = lazy(() => import('../features/strategies/StrategiesPage').then((module) => ({default: module.StrategiesPage})))
const StrategyDetailPage = lazy(() => import('../features/strategies/StrategyDetailPage').then((module) => ({default: module.StrategyDetailPage})))
const SystemPage = lazy(() => import('../features/system/SystemPage').then((module) => ({default: module.SystemPage})))
const BrokerSessionsPage = lazy(() => import('../features/broker-sessions/BrokerSessionsPage').then((module) => ({default: module.BrokerSessionsPage})))

export function AppRoutes() {
  return <Suspense fallback={<Skeleton lines={6} height={420} />}><Routes><Route element={<AppShell />}><Route index element={<Navigate to="/dashboard" replace />} /><Route path="dashboard" element={<DashboardPage />} /><Route path="strategies" element={<StrategiesPage />} /><Route path="strategies/new" element={<CreateStrategyPage />} /><Route path="strategies/:strategyId" element={<StrategyDetailPage />} /><Route path="portfolio-builder" element={<PortfolioBuilderPage />} /><Route path="portfolio" element={<PortfolioPage />} /><Route path="activity" element={<OrdersActivityPage />} /><Route path="ibkr-sessions" element={<BrokerSessionsPage />} /><Route path="system" element={<SystemPage />} /><Route path="*" element={<NotFoundPage />} /></Route></Routes></Suspense>
}
