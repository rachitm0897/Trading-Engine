import {ArrowLeft} from 'lucide-react'
import {Link} from 'react-router-dom'
import {PageHeader, Panel} from '../components/ui'

export function NotFoundPage() {
  return <div className="page-stack"><PageHeader title="Page not found" description="This trading-engine route does not exist." /><Panel><div className="empty-state"><strong>Return to an operating view</strong><Link className="button-primary" to="/dashboard"><ArrowLeft />Dashboard</Link></div></Panel></div>
}

