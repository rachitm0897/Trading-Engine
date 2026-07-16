import {useMemo, useState} from 'react'
import {useMutation, useQuery, useQueryClient} from '@tanstack/react-query'
import {ExternalLink, Filter, Search, SlidersHorizontal} from 'lucide-react'
import {mutationOptions, request} from '../../api/client'
import {queries} from '../../api/queries'
import type {Execution, Order, OrderDetail, OrderStatusHistory} from '../../api/types'
import {ActivityTimeline} from '../../components/ActivityTimeline'
import {FillProgress} from '../../components/FillProgress'
import {ConfirmActionDialog, DataTable, DetailDrawer, ErrorState, Freshness, PageHeader, Skeleton, StatusBadge, TerminalPanel, formatDateTime, formatMoney, formatNumber} from '../../components/ui'
import {useSelection} from '../../stores/useSelection'
import {canCancelOrder, canModifyOrder} from './orderEligibility'

export function OrdersActivityPage() {
  const queryClient = useQueryClient()
  const {selectedPortfolioId} = useSelection()
  const [status, setStatus] = useState('')
  const [symbol, setSymbol] = useState('')
  const [search, setSearch] = useState('')
  const [selectedOrder, setSelectedOrder] = useState<Order | null>(null)
  const [cancelOrder, setCancelOrder] = useState<Order | null>(null)
  const orders = useQuery(queries.orders({portfolioId: selectedPortfolioId, status, symbol}))
  const executions = useQuery(queries.executions({portfolioId: selectedPortfolioId, symbol}))
  const audit = useQuery(queries.audit({limit: 100}))
  const instruments = useQuery(queries.instruments())
  const orderDetail = useQuery(queries.orderDetail(selectedOrder?.internal_id || ''))
  const rows = useMemo(() => (orders.data || []).filter((order) => !search || `${order.internal_id} ${order.broker_order_id} ${order.symbol} ${order.side}`.toLowerCase().includes(search.toLowerCase())), [orders.data, search])

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({queryKey: ['orders']}),
      queryClient.invalidateQueries({queryKey: ['executions']}),
      queryClient.invalidateQueries({queryKey: ['audit']}),
      queryClient.invalidateQueries({queryKey: ['order-detail']}),
    ])
  }
  const modify = useMutation({
    mutationFn: ({order, payload}: {order: Order; payload: Record<string, string>}) => request<unknown>(`orders/${order.internal_id}/`, mutationOptions('PATCH', payload, true)),
    onSuccess: refresh,
  })
  const cancel = useMutation({
    mutationFn: ({order, reason}: {order: Order; reason: string}) => request<unknown>(`orders/${order.internal_id}/cancel/`, mutationOptions('POST', {reason}, true)),
    onSuccess: async () => {setCancelOrder(null); setSelectedOrder(null); await refresh()},
  })
  const createOrder = useMutation({
    mutationFn: (payload: Record<string, string | number>) => request<{internal_id: string; status: string; decision?: string}>('orders/', mutationOptions('POST', {portfolio_id: selectedPortfolioId, ...payload}, true)),
    onSuccess: refresh,
  })

  const orderColumns = [
    {id: 'order', header: 'Order', cell: (order: Order) => <div className="primary-cell"><button className="link-button mono" onClick={() => setSelectedOrder(order)}>{order.internal_id.slice(0, 12)}</button><span>{order.broker_order_id ? `Broker ${order.broker_order_id}` : 'Awaiting broker ID'}</span></div>},
    {id: 'instrument', header: 'Instrument', cell: (order: Order) => <div className="primary-cell"><strong className="mono">{order.symbol}</strong><span>{order.side} · {order.order_type} · {order.time_in_force}</span></div>},
    {id: 'status', header: 'Status', cell: (order: Order) => <StatusBadge status={order.status} />},
    {id: 'fill', header: 'Fill progress', cell: (order: Order) => <FillProgress filled={order.filled_quantity} total={order.quantity} />},
    {id: 'price', header: 'Average fill', align: 'right' as const, className: 'mono', cell: (order: Order) => formatMoney(order.average_fill_price)},
    {id: 'updated', header: 'Updated', cell: (order: Order) => formatDateTime(order.updated_at)},
    {id: 'view', header: '', align: 'right' as const, cell: (order: Order) => <button className="button-quiet" aria-label={`Inspect order ${order.internal_id}`} onClick={() => setSelectedOrder(order)}>Inspect<ExternalLink /></button>},
  ]
  const executionColumns = [
    {id: 'execution', header: 'Execution', cell: (fill: Execution) => <div className="primary-cell"><strong className="mono">{fill.execution_id}</strong><span>Order {fill.order_id.slice(0, 12)}</span></div>},
    {id: 'instrument', header: 'Instrument', cell: (fill: Execution) => <code>{fill.symbol}</code>},
    {id: 'quantity', header: 'Quantity', align: 'right' as const, className: 'mono', cell: (fill: Execution) => formatNumber(fill.quantity)},
    {id: 'price', header: 'Price', align: 'right' as const, className: 'mono', cell: (fill: Execution) => formatMoney(fill.price, fill.currency)},
    {id: 'commission', header: 'Commission', align: 'right' as const, className: 'mono', cell: (fill: Execution) => formatMoney(fill.commission, fill.currency)},
    {id: 'time', header: 'Executed', cell: (fill: Execution) => formatDateTime(fill.executed_at)},
  ]
  const activity = (audit.data || []).map((item) => ({id: item.id, time: item.created_at, type: item.event_type, title: item.event_type.replaceAll('.', ' '), detail: `${item.actor} · ${item.aggregate_type} ${item.aggregate_id}`}))

  return <div className="page-stack">
    <PageHeader eyebrow="OMS & ledger" title="Orders & Activity" description="Follow order progress, executions, and normal operational activity in one place." actions={<Freshness updatedAt={Math.max(orders.dataUpdatedAt, executions.dataUpdatedAt, audit.dataUpdatedAt)} stale={orders.isStale || executions.isStale || audit.isStale} fetching={orders.isFetching || executions.isFetching || audit.isFetching} onRefresh={() => void refresh()} />} />
    <TerminalPanel id="orders-blotter" title="Order blotter" description="Orders for the selected portfolio">
      <div className="filter-bar"><label className="search-field"><Search /><span className="sr-only">Search orders</span><input aria-label="Search orders" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search order, broker ID, or symbol" /></label><label><Filter /><span className="sr-only">Filter order status</span><select aria-label="Filter order status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option>{['QUEUED', 'SUBMITTED', 'ACKNOWLEDGED', 'PARTIALLY_FILLED', 'FILLED', 'CANCEL_PENDING', 'CANCELLED', 'REJECTED', 'UNKNOWN'].map((value) => <option key={value}>{value}</option>)}</select></label><label><span className="sr-only">Filter symbol</span><input aria-label="Filter symbol" value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} placeholder="Ticker" /></label><span className="filter-count">{rows.length} orders</span></div>
      {orders.isLoading ? <Skeleton lines={6} height={330} /> : orders.isError ? <ErrorState title="Orders are unavailable" error={orders.error} onRetry={() => void orders.refetch()} /> : <DataTable rows={rows} columns={orderColumns} getRowKey={(order) => order.internal_id} emptyTitle="No orders match" emptyDescription="Try clearing the filters or wait for a strategy target to reach OMS." />}
    </TerminalPanel>
    <div className="activity-grid"><TerminalPanel id="executions" title="Executions" description="Append-only broker fill ledger">{executions.isLoading ? <Skeleton lines={4} /> : executions.isError ? <ErrorState error={executions.error} onRetry={() => void executions.refetch()} compact /> : <DataTable rows={executions.data || []} columns={executionColumns} getRowKey={(fill) => fill.execution_id} emptyTitle="No executions" />}</TerminalPanel><TerminalPanel id="operational-activity" title="Operational activity" description="Recent audit events">{audit.isError ? <ErrorState error={audit.error} onRetry={() => void audit.refetch()} compact /> : <ActivityTimeline items={activity.slice(0, 12)} />}</TerminalPanel></div>
    <TerminalPanel id="manual-order-ticket" title="Manual order ticket" description="Advanced operator action. Manual orders still run pre-trade risk and use an idempotency key." defaultOpen={false}><ManualOrderTicket instruments={instruments.data || []} pending={createOrder.isPending} error={createOrder.error} result={createOrder.data} onSubmit={(payload) => createOrder.mutate(payload)} /></TerminalPanel>
    <OrderDrawer order={selectedOrder} detail={orderDetail.data} detailLoading={orderDetail.isLoading} executions={(executions.data || []).filter((fill) => fill.order_id === selectedOrder?.internal_id)} modifying={modify.isPending} error={modify.error || cancel.error || orderDetail.error} onClose={() => setSelectedOrder(null)} onModify={(payload) => selectedOrder && modify.mutate({order: selectedOrder, payload})} onCancel={() => selectedOrder && setCancelOrder(selectedOrder)} />
    <ConfirmActionDialog open={Boolean(cancelOrder)} title={`Cancel ${cancelOrder?.symbol || ''} order?`} description="Cancellation is submitted through OMS and Gateway. A fill may still arrive while the cancel is pending." confirmLabel="Request cancellation" pending={cancel.isPending} onClose={() => setCancelOrder(null)} onConfirm={(reason) => {if (cancelOrder) cancel.mutate({order: cancelOrder, reason})}} />
  </div>
}

function orderHistoryItem(item: OrderStatusHistory) {
  const reason = item.reason || 'No broker reason received'
  const code = item.reason_code ? `Code ${item.reason_code} · ` : ''
  const broker = item.broker_status ? ` · IBKR ${item.broker_status}` : ''
  const operator = item.operator_requested ? ' · operator requested' : ''
  return {id:item.id,time:item.occurred_at,type:'ORDER_STATUS',title:`${item.from_status || 'START'} → ${item.to_status}`,
    status:item.to_status,detail:`${code}${reason} · ${item.source}${broker}${operator}`}
}

function OrderDrawer({order, detail, detailLoading, executions, modifying, error, onClose, onModify, onCancel}: {order: Order | null; detail?: OrderDetail; detailLoading: boolean; executions: Execution[]; modifying: boolean; error: unknown; onClose: () => void; onModify: (payload: Record<string, string>) => void; onCancel: () => void}) {
  if (!order) return null
  const submit = (event: React.FormEvent<HTMLFormElement>) => {event.preventDefault(); const form = new FormData(event.currentTarget); const payload: Record<string, string> = {quantity: String(form.get('quantity')), time_in_force: String(form.get('time_in_force'))}; if (form.get('limit_price')) payload.limit_price = String(form.get('limit_price')); onModify(payload)}
  return <DetailDrawer open title={`${order.symbol} ${order.side}`} subtitle={order.internal_id} onClose={onClose} footer={<div className="drawer-actions"><button className="button-danger-subtle" disabled={!canCancelOrder(order)} onClick={onCancel}>Cancel order</button></div>}><div className="order-summary"><StatusBadge status={order.status} /><FillProgress filled={order.filled_quantity} total={order.quantity} /><dl className="detail-list"><div><dt>Type</dt><dd>{order.order_type}</dd></div><div><dt>Time in force</dt><dd>{order.time_in_force}</dd></div><div><dt>Broker order ID</dt><dd><code>{order.broker_order_id || 'Pending'}</code></dd></div><div><dt>Average fill</dt><dd className="mono">{formatMoney(order.average_fill_price)}</dd></div><div><dt>Created</dt><dd>{formatDateTime(order.created_at)}</dd></div><div><dt>Updated</dt><dd>{formatDateTime(order.updated_at)}</dd></div></dl></div>{canModifyOrder(order) ? <form className="drawer-form" onSubmit={submit}><h3>Modify eligible fields</h3><label>Total quantity<input name="quantity" type="number" min={Number(order.filled_quantity)} step="any" defaultValue={String(order.quantity)} required /></label><label>Limit price<input name="limit_price" type="number" min="0" step="any" /></label><label>Time in force<select name="time_in_force" defaultValue={order.time_in_force}><option>DAY</option><option>GTC</option></select></label><button className="button-primary" disabled={modifying}>{modifying ? 'Submitting…' : 'Submit modification'}</button></form> : <div className="inline-note">This order’s current state does not permit modification.</div>}{error ? <ErrorState title="Order action failed" error={error} compact /> : null}<h3>Status timeline</h3>{detailLoading ? <Skeleton lines={3} /> : <ActivityTimeline items={(detail?.status_history || []).map(orderHistoryItem)} emptyDescription="No order status has been persisted." />}<h3>Fills</h3><DataTable rows={executions} columns={[{id: 'id', header: 'Execution', cell: (fill) => <code>{fill.execution_id}</code>}, {id: 'qty', header: 'Quantity', cell: (fill) => formatNumber(fill.quantity)}, {id: 'price', header: 'Price', cell: (fill) => formatMoney(fill.price, fill.currency)}, {id: 'time', header: 'Time', cell: (fill) => formatDateTime(fill.executed_at)}]} getRowKey={(fill) => fill.execution_id} emptyTitle="No fills for this order" /></DetailDrawer>
}

function ManualOrderTicket({instruments, pending, error, result, onSubmit}: {instruments: {id: number; symbol: string; exchange: string}[]; pending: boolean; error: unknown; result?: {internal_id: string; status: string; decision?: string}; onSubmit: (payload: Record<string, string | number>) => void}) {
  const submit = (event: React.FormEvent<HTMLFormElement>) => {event.preventDefault(); const form = new FormData(event.currentTarget); onSubmit({instrument_id: Number(form.get('instrument_id')), side: String(form.get('side')), order_type: String(form.get('order_type')), quantity: String(form.get('quantity')), reference_price: String(form.get('reference_price')), time_in_force: String(form.get('time_in_force'))})}
  return <><form className="form-grid four-columns" onSubmit={submit}><label>Instrument<select name="instrument_id" required><option value="">Choose</option>{instruments.map((instrument) => <option key={instrument.id} value={instrument.id}>{instrument.symbol} · {instrument.exchange}</option>)}</select></label><label>Side<select name="side"><option>BUY</option><option>SELL</option></select></label><label>Type<select name="order_type"><option>MKT</option><option>LMT</option><option>STP</option><option>STP_LMT</option></select></label><label>Quantity<input aria-label="Quantity" name="quantity" type="number" min="0.00000001" step="any" required /></label><label>Reference price<input aria-label="Reference price" name="reference_price" type="number" min="0.00000001" step="any" required /></label><label>Time in force<select name="time_in_force"><option>DAY</option><option>GTC</option></select></label><button className="button-primary form-submit" disabled={pending}><SlidersHorizontal />{pending ? 'Running risk…' : 'Submit to risk'}</button></form>{error && <ErrorState title="Manual order was blocked" error={error} compact />}{result && <div className="inline-success"><StatusBadge status={result.decision || result.status} />Order <code>{result.internal_id}</code> entered OMS.</div>}</>
}
