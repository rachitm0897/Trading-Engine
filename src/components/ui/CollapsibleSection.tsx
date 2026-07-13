import type {ReactNode} from 'react'
import {ChevronDown} from 'lucide-react'

interface CollapsibleSectionProps {
  title: string
  description?: string
  children: ReactNode
  defaultOpen?: boolean
  badge?: ReactNode
}

export function CollapsibleSection({title, description, children, defaultOpen = false, badge}: CollapsibleSectionProps) {
  return (
    <details className="collapsible" open={defaultOpen}>
      <summary><div><strong>{title}</strong>{description && <span>{description}</span>}</div>{badge}<ChevronDown aria-hidden="true" /></summary>
      <div className="collapsible-content">{children}</div>
    </details>
  )
}

