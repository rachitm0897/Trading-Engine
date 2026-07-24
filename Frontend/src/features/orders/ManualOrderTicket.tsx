import {AlertTriangle, ShieldCheck, SlidersHorizontal, X} from 'lucide-react'
import {useMemo, useState} from 'react'
import {ApiError} from '../../api/client'
import type {
  Instrument,
  ManualOrderIntentStatus,
  Position,
} from '../../api/types'
import {StatusBadge, formatMoney, formatNumber} from '../../components/ui'
import {
  buildManualOrderPayload,
  estimateManualOrderNotional,
  initialManualOrderDraft,
  manualOrderBlockingReasons,
  manualOrderResultKind,
  orderTypeNeedsLimitPrice,
  orderTypeNeedsStopPrice,
  validateManualOrderDraft,
  type ManualOrderDraft,
  type ManualOrderPayload,
  type ManualOrderSelection,
  type ManualOrderType,
} from './manualOrder'

interface ManualOrderTicketProps extends ManualOrderSelection {
  instruments: Instrument[]
  positions: Position[]
  pending: boolean
  polling: boolean
  pollTimedOut: boolean
  error: unknown
  result?: ManualOrderIntentStatus
  onSubmit: (payload: ManualOrderPayload) => void
}

export function ManualOrderTicket({
  instruments,
  positions,
  session,
  account,
  portfolio,
  pending,
  polling,
  pollTimedOut,
  error,
  result,
  onSubmit,
}: ManualOrderTicketProps) {
  const [draft, setDraft] = useState<ManualOrderDraft>(initialManualOrderDraft)
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({})
  const [confirmation, setConfirmation] = useState<ManualOrderDraft | null>(null)
  const instrument = instruments.find((item) => item.id === Number(draft.instrumentId)) || null
  const position = positions.find((item) => item.instrument_id === instrument?.id)
  const blockers = manualOrderBlockingReasons({session, account, portfolio})
  const estimatedNotional = estimateManualOrderNotional(draft, position?.market_price)
  const busy = pending || polling

  const update = <K extends keyof ManualOrderDraft>(field: K, value: ManualOrderDraft[K]) => {
    setDraft((current) => ({...current, [field]: value}))
    setValidationErrors((current) => {
      if (!current[field]) return current
      const next = {...current}
      delete next[field]
      return next
    })
  }
  const changeOrderType = (orderType: ManualOrderType) => {
    setDraft((current) => ({
      ...current,
      orderType,
      limitPrice: orderTypeNeedsLimitPrice(orderType) ? current.limitPrice : '',
      stopPrice: orderTypeNeedsStopPrice(orderType) ? current.stopPrice : '',
    }))
    setValidationErrors({})
  }
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextErrors = validateManualOrderDraft(draft, instruments)
    setValidationErrors(nextErrors)
    if (Object.keys(nextErrors).length || blockers.length || busy) return
    setConfirmation({...draft})
  }
  const confirm = () => {
    if (!confirmation || busy) return
    setConfirmation(null)
    onSubmit(buildManualOrderPayload(confirmation))
  }

  return <>
    <div className="manual-order-context" aria-label="Manual order routing context">
      <ContextValue label="Session" value={session?.display_name || 'Not selected'} detail={session ? session.status : undefined} />
      <ContextValue label="Mode" value={session?.mode.toUpperCase() || '—'} critical={session?.mode.toLowerCase() === 'live'} />
      <ContextValue label="Account" value={account?.account_id || 'Not selected'} detail={account?.alias} />
      <ContextValue label="Portfolio" value={portfolio?.name || 'Not selected'} />
    </div>
    {session?.mode.toLowerCase() === 'live' && <div className="inline-warning manual-live-warning"><AlertTriangle /><div><strong>LIVE routing is disabled</strong><p>The backend policy rejects LIVE manual orders. Select a connected PAPER session.</p></div></div>}
    {blockers.length > 0 && <div className="manual-order-blockers" role="status"><strong>Submission unavailable</strong><ul>{blockers.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}
    <form className="form-grid four-columns manual-order-form" onSubmit={submit} noValidate>
      <label>Instrument
        <select aria-label="Instrument" value={draft.instrumentId} onChange={(event) => update('instrumentId', event.target.value)} aria-invalid={Boolean(validationErrors.instrumentId)}>
          <option value="">Choose</option>
          {instruments.map((item) => <option key={item.id} value={item.id} disabled={!item.active || !item.tradable}>{item.symbol} · {item.exchange}{!item.active ? ' · inactive' : !item.tradable ? ' · not tradable' : ''}</option>)}
        </select>
        {validationErrors.instrumentId && <span className="field-error">{validationErrors.instrumentId}</span>}
      </label>
      <label>Side
        <select aria-label="Side" value={draft.side} onChange={(event) => update('side', event.target.value as ManualOrderDraft['side'])} aria-invalid={Boolean(validationErrors.side)}><option>BUY</option><option>SELL</option></select>
        {validationErrors.side && <span className="field-error">{validationErrors.side}</span>}
      </label>
      <label>Order type
        <select aria-label="Order type" value={draft.orderType} onChange={(event) => changeOrderType(event.target.value as ManualOrderType)} aria-invalid={Boolean(validationErrors.orderType)}><option>MKT</option><option>LMT</option><option>STP</option><option>STP_LMT</option></select>
        {validationErrors.orderType && <span className="field-error">{validationErrors.orderType}</span>}
      </label>
      <label>Quantity
        <input aria-label="Quantity" value={draft.quantity} onChange={(event) => update('quantity', event.target.value)} type="number" min="0.00000001" step="0.00000001" inputMode="decimal" aria-invalid={Boolean(validationErrors.quantity)} />
        {validationErrors.quantity && <span className="field-error">{validationErrors.quantity}</span>}
      </label>
      {orderTypeNeedsStopPrice(draft.orderType) && <label>Stop price
        <input aria-label="Stop price" value={draft.stopPrice} onChange={(event) => update('stopPrice', event.target.value)} type="number" min="0.00000001" step="0.00000001" inputMode="decimal" aria-invalid={Boolean(validationErrors.stopPrice)} />
        {validationErrors.stopPrice && <span className="field-error">{validationErrors.stopPrice}</span>}
      </label>}
      {orderTypeNeedsLimitPrice(draft.orderType) && <label>Limit price
        <input aria-label="Limit price" value={draft.limitPrice} onChange={(event) => update('limitPrice', event.target.value)} type="number" min="0.00000001" step="0.00000001" inputMode="decimal" aria-invalid={Boolean(validationErrors.limitPrice)} />
        {validationErrors.limitPrice && <span className="field-error">{validationErrors.limitPrice}</span>}
      </label>}
      <label>Time in force
        <select aria-label="Time in force" value={draft.timeInForce} onChange={(event) => update('timeInForce', event.target.value as ManualOrderDraft['timeInForce'])} aria-invalid={Boolean(validationErrors.timeInForce)}><option>DAY</option><option>GTC</option></select>
        {validationErrors.timeInForce && <span className="field-error">{validationErrors.timeInForce}</span>}
      </label>
      <div className="manual-order-estimate">
        <span>Estimated notional</span>
        <strong>{estimatedNotional === null ? 'Available after a safe price is known' : formatMoney(estimatedNotional, instrument?.currency)}</strong>
        {draft.side === 'SELL' && <small>Available position: {position ? formatNumber(position.quantity) : 'No position reported'}</small>}
      </div>
      <button className="button-primary form-submit" disabled={busy || blockers.length > 0}><SlidersHorizontal />{pending ? 'Submitting…' : polling ? 'Awaiting OMS…' : 'Review manual order'}</button>
    </form>
    <p className="manual-order-risk-note"><ShieldCheck />Final quantity may be resized by the common pre-trade risk pipeline.</p>
    <ManualOrderError error={error} />
    {result && <ManualOrderResult result={result} polling={polling} pollTimedOut={pollTimedOut} />}
    {pollTimedOut && !result?.internal_id && <div className="inline-warning" role="status"><AlertTriangle /><div><strong>Status polling timed out</strong><p>The intent was not submitted again. Refresh Orders & Activity or check the intent ID below.</p></div></div>}
    {confirmation && <ManualOrderConfirmation
      draft={confirmation}
      instrument={instruments.find((item) => item.id === Number(confirmation.instrumentId)) || null}
      sessionName={session?.display_name || 'Not selected'}
      mode={session?.mode.toUpperCase() || '—'}
      accountName={account?.account_id || 'Not selected'}
      portfolioName={portfolio?.name || 'Not selected'}
      estimatedNotional={estimateManualOrderNotional(confirmation, position?.market_price)}
      pending={pending}
      onClose={() => setConfirmation(null)}
      onConfirm={confirm}
    />}
  </>
}

function ContextValue({label, value, detail, critical = false}: {label: string; value: string; detail?: string; critical?: boolean}) {
  return <div><span>{label}</span><strong className={critical ? 'critical-text' : ''}>{value}</strong>{detail && <small>{detail}</small>}</div>
}

function ManualOrderConfirmation({
  draft,
  instrument,
  sessionName,
  mode,
  accountName,
  portfolioName,
  estimatedNotional,
  pending,
  onClose,
  onConfirm,
}: {
  draft: ManualOrderDraft
  instrument: Instrument | null
  sessionName: string
  mode: string
  accountName: string
  portfolioName: string
  estimatedNotional: number | null
  pending: boolean
  onClose: () => void
  onConfirm: () => void
}) {
  const rows = useMemo(() => [
    ['Route', `${sessionName} · ${mode}`],
    ['Account', accountName],
    ['Portfolio', portfolioName],
    ['Instrument', instrument ? `${instrument.symbol} · ${instrument.exchange}` : 'Not selected'],
    ['Order', `${draft.side} ${draft.quantity} ${draft.orderType}`],
    ...(orderTypeNeedsStopPrice(draft.orderType) ? [['Stop price', draft.stopPrice]] : []),
    ...(orderTypeNeedsLimitPrice(draft.orderType) ? [['Limit price', draft.limitPrice]] : []),
    ['Time in force', draft.timeInForce],
    ['Estimated notional', estimatedNotional === null ? 'Not available' : formatMoney(estimatedNotional, instrument?.currency)],
  ], [accountName, draft, estimatedNotional, instrument, mode, portfolioName, sessionName])
  return <div className="dialog-layer" role="presentation">
    <div className="confirm-dialog manual-order-confirmation" role="dialog" aria-modal="true" aria-labelledby="manual-order-confirm-title">
      <header><AlertTriangle /><div><h2 id="manual-order-confirm-title">Confirm manual order</h2><p>Review the exact order routed through risk, OMS, and the selected Gateway.</p></div><button type="button" className="icon-button" aria-label="Close manual order confirmation" onClick={onClose}><X /></button></header>
      <dl className="detail-list">{rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      <div className="inline-warning"><AlertTriangle /><div><strong>Risk may resize or reject this order</strong><p>Confirmation creates one durable manual OrderIntent; it does not bypass backend validation.</p></div></div>
      <footer><button type="button" className="button-secondary" onClick={onClose}>Go back</button><button type="button" className="button-primary" disabled={pending} onClick={onConfirm}>{pending ? 'Submitting…' : 'Confirm and queue'}</button></footer>
    </div>
  </div>
}

function ManualOrderResult({result, polling, pollTimedOut}: {result: ManualOrderIntentStatus; polling: boolean; pollTimedOut: boolean}) {
  const kind = manualOrderResultKind(result)
  if (kind === 'OMS') return <div className="manual-order-result inline-success" role="status">
    <StatusBadge status={result.status || result.operation_status} />
    <div><strong>Manual order entered OMS.</strong><p>Internal order <code>{result.internal_id}</code> · intent <code>{result.intent_id}</code> · origin {result.origin}</p><p>Current status: {result.status} · approved quantity: {formatNumber(result.approved_quantity)}</p>{result.broker_command && <p>Broker command: {result.broker_command.command_type} · {result.broker_command.status}</p>}</div>
  </div>
  if (kind === 'HELD') return <div className="manual-order-result inline-warning" role="status">
    <AlertTriangle /><div><strong>HELD · {result.operation_status}</strong><p>{result.message}</p><p>Intent <code>{result.intent_id}</code> · origin {result.origin} · the system will retry: {result.retryable ? 'yes' : 'no'}{polling ? ' · polling durable status' : ''}</p></div>
  </div>
  if (kind === 'REJECTED') return <div className="manual-order-result manual-order-rejected" role="alert">
    <StatusBadge status="REJECTED" /><div><strong>RISK_REJECTED</strong><p>{result.message}</p><p>Intent <code>{result.intent_id}</code> · origin {result.origin} · retryable: {result.retryable ? 'yes' : 'no'}</p></div>
  </div>
  return <div className="manual-order-result manual-order-queued" role="status">
    <StatusBadge status={result.operation_status} /><div><strong>Manual order accepted and queued for risk and execution.</strong><p>Intent <code>{result.intent_id}</code> · origin {result.origin}</p><p>Operation: {result.operation_status} · retryable: {result.retryable ? 'yes' : 'no'}{polling ? ' · polling durable status' : pollTimedOut ? ' · polling stopped' : ''}</p><p>{result.message}</p></div>
  </div>
}

function ManualOrderError({error}: {error: unknown}) {
  if (!error) return null
  const apiError = error instanceof ApiError ? error : null
  const code = apiError?.code || 'REQUEST_FAILED'
  const message = error instanceof Error ? error.message : 'The manual order request failed.'
  const explanation = specificErrorExplanation(code, message)
  return <div className="manual-order-api-error" role="alert">
    <StatusBadge status="REJECTED" />
    <div><strong>{code}</strong><p>{apiError ? `HTTP ${apiError.status || 'network'} · ` : ''}{message}</p>{explanation !== message && <p>{explanation}</p>}{apiError?.details !== null && apiError?.details !== undefined && <details><summary>Structured details</summary><pre>{JSON.stringify(apiError.details, null, 2)}</pre></details>}</div>
  </div>
}

function specificErrorExplanation(code: string, message: string) {
  const value = `${code} ${message}`.toLowerCase()
  if (code === 'IDEMPOTENCY_CONFLICT') return 'This idempotency key was already used for materially different order contents. Review the form and start a new submission.'
  if (code === 'LIVE_MANUAL_TRADING_DISABLED' || value.includes('live manual')) return 'LIVE manual routing is disabled. Select an eligible PAPER session.'
  if (code === 'MARKET_PRICE_UNAVAILABLE' || value.includes('stale') || value.includes('market price')) return 'A sufficiently fresh trusted market price is unavailable; no client reference price will be substituted.'
  if (value.includes('reconcil')) return 'The selected account must complete reconciliation before commands can be dispatched.'
  if (value.includes('disconnected') || value.includes('not active') || value.includes('gateway')) return 'Reconnect the selected Gateway session and verify commands are enabled.'
  if (value.includes('cash') || value.includes('buying power')) return 'Risk reported insufficient available cash or buying power for this order.'
  if (value.includes('position') || value.includes('short')) return 'Risk reported insufficient unreserved position quantity for this SELL order.'
  if (value.includes('inactive') || value.includes('tradable')) return 'The selected instrument is inactive or not tradable.'
  if (value.includes('kill switch')) return 'A kill switch is preventing execution for the selected route.'
  if (code === 'RISK_REJECTED' || value.includes('risk')) return 'The common pre-trade risk policy rejected this intent.'
  return message
}
