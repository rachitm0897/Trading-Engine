from decimal import Decimal
from django.utils import timezone
import pytest
from apps.accounts.models import BrokerAccount
from apps.execution.models import Fill
from apps.instruments.models import Instrument
from apps.oms.models import OrderIntent
from apps.oms.services import apply_execution, create_order, transition
from apps.portfolios.models import TradingPortfolio, CashLedgerEntry, PositionLedgerEntry
from apps.risk.services import evaluate_intent

pytestmark = pytest.mark.django_db

@pytest.fixture
def intent():
    account = BrokerAccount.objects.create(account_id="DU123", is_reconciled=True)
    portfolio = TradingPortfolio.objects.create(name="Paper", account=account)
    instrument = Instrument.objects.create(symbol="AAPL")
    return OrderIntent.objects.create(portfolio=portfolio, instrument=instrument, side="BUY", quantity=10, idempotency_key="intent-1")

def test_risk_approval_resize_and_kill_switch(intent):
    decision, qty, _ = evaluate_intent(intent, {"max_quantity":20}, {"connected":True, "reconciled":True})
    assert (decision, qty) == ("APPROVED", Decimal("10"))
    intent.risk_checks.all().delete()
    decision, qty, _ = evaluate_intent(intent, {"max_quantity":5}, {"connected":True, "reconciled":True})
    assert (decision, qty) == ("RESIZED", Decimal("5"))
    intent.portfolio.kill_switch=True; intent.portfolio.save()
    assert evaluate_intent(intent, {}, {"connected":True, "reconciled":True})[0] == "REJECTED"

def test_partial_fill_is_idempotent_and_updates_ledgers(intent):
    order = create_order(intent); order.status="ACKNOWLEDGED"; order.save()
    event = {"execution_id":"E1", "quantity":"4", "price":"100", "commission":"1", "executed_at":timezone.now()}
    apply_execution(order, event); apply_execution(order, event)
    order.refresh_from_db()
    assert order.status == "PARTIALLY_FILLED" and order.filled_quantity == 4
    assert Fill.objects.count() == CashLedgerEntry.objects.count() == PositionLedgerEntry.objects.count() == 1

def test_queued_order_can_enter_cancel_pending(intent):
    order=create_order(intent); order=transition(order,"QUEUED","oms","queued")
    assert transition(order,"CANCEL_PENDING","operator","cancel").status=="CANCEL_PENDING"
