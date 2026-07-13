export type StatusTone = 'positive' | 'warning' | 'critical' | 'neutral' | 'info'

function inferTone(status: string): StatusTone {
  const value = status.toUpperCase()
  if (/CONNECTED|RECONCILED|HEALTHY|APPROVED|FILLED|COMPLETED|ACTIVE|FRESH|PAPER/.test(value)) return 'positive'
  if (/ERROR|REJECT|BLOCK|KILL|DISCONNECT|FAILED|CRITICAL|STALE/.test(value)) return 'critical'
  if (/PENDING|PARTIAL|WARM|UNKNOWN|DEGRADED|HELD|PAUSED|CANCEL/.test(value)) return 'warning'
  if (/SHADOW|OBSERVE|INFO/.test(value)) return 'info'
  return 'neutral'
}

export function StatusBadge({status, tone}: {status?: string | null; tone?: StatusTone}) {
  const label = status || 'Unknown'
  return <span className={`status-badge status-${tone || inferTone(label)}`}><span aria-hidden="true" />{label.replaceAll('_', ' ')}</span>
}

