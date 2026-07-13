import type {ReactNode} from 'react'

interface MetricCardProps {
  label: string
  value: ReactNode
  helper?: ReactNode
  icon?: ReactNode
  trend?: 'positive' | 'negative' | 'neutral'
}

export function MetricCard({label, value, helper, icon, trend = 'neutral'}: MetricCardProps) {
  return (
    <article className="metric-card">
      <div className="metric-card-label">{label}{icon && <span className="metric-card-icon">{icon}</span>}</div>
      <div className={`metric-card-value metric-${trend}`}>{value}</div>
      {helper && <div className="metric-card-helper">{helper}</div>}
    </article>
  )
}

