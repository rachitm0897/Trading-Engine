import json, uuid
from decimal import Decimal
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from apps.audit.models import AuditEvent, OutboxEvent
from apps.execution.models import Fill
from apps.portfolios.models import CashLedgerEntry, PortfolioPosition, PositionLedgerEntry
from .models import Order, OrderStatusHistory

ALLOWED = {
 "CREATED": {"RISK_APPROVED", "REJECTED", "BROKER_BLOCKED"}, "RISK_APPROVED": {"QUEUED"},
 "QUEUED": {"SUBMITTED", "BROKER_BLOCKED", "REJECTED", "CANCEL_PENDING"}, "BROKER_BLOCKED": {"QUEUED", "REJECTED"},
 "SUBMITTED": {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "REJECTED", "UNKNOWN", "CANCEL_PENDING"},
 "ACKNOWLEDGED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "EXPIRED", "UNKNOWN"},
 "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "CANCEL_PENDING", "CANCELLED", "UNKNOWN"},
 "CANCEL_PENDING": {"CANCELLED", "FILLED", "UNKNOWN"}, "UNKNOWN": {"ACKNOWLEDGED", "PARTIALLY_FILLED", "FILLED", "CANCELLED"},
}

@transaction.atomic
def create_order(intent, quantity=None):
    order, created = Order.objects.get_or_create(intent=intent, defaults={"internal_id": str(uuid.uuid4()), "quantity": quantity or intent.quantity})
    if created:
        transition(order, "RISK_APPROVED", "risk", f"order:{order.internal_id}:approved")
        OutboxEvent.objects.create(topic="order.created", aggregate_id=order.internal_id, payload={"order_id": order.internal_id}, idempotency_key=f"outbox:order:{order.internal_id}:created")
    return order

@transaction.atomic
def transition(order, new_status, source, event_key, reason=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    history, created = OrderStatusHistory.objects.get_or_create(event_key=event_key, defaults={"order": order, "from_status": order.status, "to_status": new_status, "source": source, "reason": reason})
    if not created: return order
    if new_status not in ALLOWED.get(order.status, set()): raise ValueError(f"Invalid order transition {order.status} -> {new_status}")
    order.status = new_status; order.save(update_fields=["status", "updated_at"])
    return order

@transaction.atomic
def apply_execution(order, execution):
    order = Order.objects.select_for_update().select_related("intent__portfolio", "intent__instrument").get(pk=order.pk)
    raw_event = json.loads(json.dumps(execution, cls=DjangoJSONEncoder))
    fill, created = Fill.objects.get_or_create(execution_id=execution["execution_id"], defaults={"order": order, "quantity": Decimal(str(execution["quantity"])), "price": Decimal(str(execution["price"])), "commission": Decimal(str(execution.get("commission", 0))), "currency": execution.get("currency", "USD"), "executed_at": execution.get("executed_at", timezone.now()), "raw_event": raw_event})
    if not created: return fill
    old_qty = order.filled_quantity; new_qty = old_qty + fill.quantity
    order.average_fill_price = ((order.average_fill_price * old_qty) + (fill.price * fill.quantity)) / new_qty
    order.filled_quantity = new_qty; order.save(update_fields=["filled_quantity", "average_fill_price", "updated_at"])
    status = "FILLED" if new_qty >= order.quantity else "PARTIALLY_FILLED"
    transition(order, status, "execution", f"execution:{fill.execution_id}")
    signed_qty = fill.quantity if order.intent.side == "BUY" else -fill.quantity
    cash = -(signed_qty * fill.price) - fill.commission
    PositionLedgerEntry.objects.create(portfolio=order.intent.portfolio, instrument=order.intent.instrument, quantity_delta=signed_qty, price=fill.price, kind="FILL", reference=fill.execution_id, idempotency_key=f"position:{fill.execution_id}")
    CashLedgerEntry.objects.create(portfolio=order.intent.portfolio, amount=cash, currency=fill.currency, kind="FILL", reference=fill.execution_id, idempotency_key=f"cash:{fill.execution_id}")
    position, _ = PortfolioPosition.objects.select_for_update().get_or_create(portfolio=order.intent.portfolio, instrument=order.intent.instrument)
    position.quantity += signed_qty; position.market_price = fill.price; position.save(update_fields=["quantity", "market_price", "updated_at"])
    AuditEvent.objects.create(event_type="fill.recorded", actor="broker", aggregate_type="order", aggregate_id=order.internal_id, data={"execution_id": fill.execution_id}, idempotency_key=f"audit:fill:{fill.execution_id}")
    return fill
