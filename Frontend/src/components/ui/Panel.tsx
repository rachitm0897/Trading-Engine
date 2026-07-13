import type {ReactNode} from 'react'

export function Panel({title, description, actions, children, className = ''}: {title?: string; description?: string; actions?: ReactNode; children: ReactNode; className?: string}) {
  return <section className={`panel ${className}`}>{(title || actions) && <header className="panel-header"><div>{title && <h2>{title}</h2>}{description && <p>{description}</p>}</div>{actions && <div className="panel-actions">{actions}</div>}</header>}<div className="panel-content">{children}</div></section>
}

