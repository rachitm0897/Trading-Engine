from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.utils import timezone
from django.db import close_old_connections, connection
import pytest
from apps.accounts.models import BrokerAccount
from apps.execution.models import Fill
from apps.instruments.models import Instrument
from apps.oms.models import OrderIntent
from apps.oms.services import apply_execution, create_order, transition
from apps.portfolios.models import TradingPortfolio, CashLedgerEntry, PortfolioPosition, PositionLedgerEntry
from apps.risk.models import CapitalReservation, KillSwitch, PreTradeRiskPolicy
from apps.risk.services import evaluate_intent
from apps.strategies.models import StrategyDefinition, StrategyInstance

pytestmark = pytest.mark.django_db

@pytest.fixture
def intent():
    account = BrokerAccount.objects.create(account_id="DU123", available_cash=1000, is_reconciled=True)
    portfolio = TradingPortfolio.objects.create(name="Paper", account=account)
    instrument = Instrument.objects.create(symbol="AAPL")
    return OrderIntent.objects.create(portfolio=portfolio, instrument=instrument, side="BUY", quantity=10, idempotency_key="intent-1")

def test_risk_approval_resize_and_kill_switch(intent):
    policy=PreTradeRiskPolicy.objects.create(portfolio=intent.portfolio,maximum_order_quantity=20)
    decision, qty, _ = evaluate_intent(intent, {"connected":True, "reconciled":True, "mode":"paper"})
    assert (decision, qty) == ("APPROVED", Decimal("10"))
    intent.risk_checks.all().delete()
    policy.maximum_order_quantity=5;policy.save()
    decision, qty, _ = evaluate_intent(intent, {"connected":True, "reconciled":True, "mode":"paper"})
    assert (decision, qty) == ("RESIZED", Decimal("5"))
    intent.portfolio.kill_switch=True; intent.portfolio.save()
    assert evaluate_intent(intent, {"connected":True, "reconciled":True, "mode":"paper"})[0] == "REJECTED"


def test_live_gateway_session_is_always_rejected(intent):
    decision,approved,_=evaluate_intent(intent,{"connected":True,"reconciled":True,"mode":"live"})
    assert decision=="REJECTED" and approved==0

def test_partial_fill_is_idempotent_and_updates_ledgers(intent):
    order = create_order(intent); order.status="ACKNOWLEDGED"; order.save()
    event = {"execution_id":"E1", "quantity":"4", "price":"100", "commission":"1", "executed_at":timezone.now()}
    apply_execution(order, event); apply_execution(order, event)
    order.refresh_from_db()
    assert order.status == "PARTIALLY_FILLED" and order.filled_quantity == 4
    assert Fill.objects.count() == CashLedgerEntry.objects.count() == PositionLedgerEntry.objects.count() == 1


def test_partial_fills_update_weighted_average_cost(intent):
    order=create_order(intent);order.status="ACKNOWLEDGED";order.save()
    apply_execution(order,{"execution_id":"E1","quantity":"4","price":"100","executed_at":timezone.now()})
    apply_execution(order,{"execution_id":"E2","quantity":"6","price":"110","executed_at":timezone.now()})
    position=PortfolioPosition.objects.get(portfolio=intent.portfolio,instrument=intent.instrument)
    assert position.quantity==10
    assert position.average_cost==Decimal("106")
    assert position.realized_pnl==0


def test_position_reduction_keeps_average_cost_and_records_realized_pnl(intent):
    PortfolioPosition.objects.create(portfolio=intent.portfolio,instrument=intent.instrument,quantity=10,average_cost=100)
    sell=OrderIntent.objects.create(portfolio=intent.portfolio,instrument=intent.instrument,side="SELL",quantity=4,idempotency_key="sell-reduce")
    order=create_order(sell);order.status="ACKNOWLEDGED";order.save()
    apply_execution(order,{"execution_id":"SELL-1","quantity":"4","price":"130","executed_at":timezone.now()})
    position=PortfolioPosition.objects.get(portfolio=intent.portfolio,instrument=intent.instrument)
    ledger=PositionLedgerEntry.objects.get(reference="SELL-1")
    assert (position.quantity,position.average_cost,position.realized_pnl)==(6,100,120)
    assert ledger.realized_pnl==120


def test_complete_close_resets_average_cost(intent):
    PortfolioPosition.objects.create(portfolio=intent.portfolio,instrument=intent.instrument,quantity=3,average_cost=100)
    sell=OrderIntent.objects.create(portfolio=intent.portfolio,instrument=intent.instrument,side="SELL",quantity=3,idempotency_key="sell-close")
    order=create_order(sell);order.status="ACKNOWLEDGED";order.save()
    apply_execution(order,{"execution_id":"SELL-CLOSE","quantity":"3","price":"90","executed_at":timezone.now()})
    position=PortfolioPosition.objects.get(portfolio=intent.portfolio,instrument=intent.instrument)
    assert (position.quantity,position.average_cost,position.realized_pnl)==(0,0,-30)


def test_fill_crossing_zero_starts_reversed_position_at_fill_price(intent):
    PortfolioPosition.objects.create(portfolio=intent.portfolio,instrument=intent.instrument,quantity=2,average_cost=100)
    sell=OrderIntent.objects.create(portfolio=intent.portfolio,instrument=intent.instrument,side="SELL",quantity=5,idempotency_key="sell-flip")
    order=create_order(sell);order.status="ACKNOWLEDGED";order.save()
    apply_execution(order,{"execution_id":"SELL-FLIP","quantity":"5","price":"120","executed_at":timezone.now()})
    position=PortfolioPosition.objects.get(portfolio=intent.portfolio,instrument=intent.instrument)
    assert (position.quantity,position.average_cost,position.realized_pnl)==(-3,120,40)


def test_execution_failure_rolls_back_fill_order_ledgers_and_position(intent,monkeypatch):
    order=create_order(intent);order.status="ACKNOWLEDGED";order.save()
    def fail_ledger(*args,**kwargs):
        raise RuntimeError("ledger unavailable")
    monkeypatch.setattr(PositionLedgerEntry.objects,"create",fail_ledger)

    with pytest.raises(RuntimeError,match="ledger unavailable"):
        apply_execution(order,{"execution_id":"ROLLBACK","quantity":"4","price":"100","executed_at":timezone.now()})

    order.refresh_from_db()
    assert order.filled_quantity==0 and order.average_fill_price==0 and order.status=="ACKNOWLEDGED"
    assert not Fill.objects.filter(execution_id="ROLLBACK").exists()
    assert not PortfolioPosition.objects.filter(portfolio=intent.portfolio,instrument=intent.instrument).exists()
    assert CashLedgerEntry.objects.count()==PositionLedgerEntry.objects.count()==0

def test_queued_order_can_enter_cancel_pending(intent):
    order=create_order(intent); order=transition(order,"QUEUED","oms","queued")
    assert transition(order,"CANCEL_PENDING","operator","cancel").status=="CANCEL_PENDING"


def test_invalid_order_transition_is_rejected_without_history_side_effect(intent):
    order=create_order(intent)
    before=order.status_history.count()
    with pytest.raises(ValueError,match="Invalid order transition RISK_APPROVED -> FILLED"):
        transition(order,"FILLED","test","invalid-direct-fill")
    order.refresh_from_db()
    assert order.status=="RISK_APPROVED"
    assert order.status_history.count()==before


@pytest.mark.parametrize("scope",["GLOBAL","ACCOUNT","PORTFOLIO","STRATEGY","INSTRUMENT"])
def test_kill_switch_blocks_only_when_its_scope_matches(intent,scope):
    strategy=StrategyInstance.objects.create(name="Scoped",definition=StrategyDefinition.objects.get(key="FIXED_WEIGHT_REBALANCE"),
        portfolio=intent.portfolio,instrument=intent.instrument,timeframe="1d",parameters={"direction":"LONG"})
    intent.strategy_instance=strategy;intent.reference_price=10;intent.save(update_fields=["strategy_instance","reference_price"])
    matching={
        "GLOBAL":"",
        "ACCOUNT":intent.portfolio.account.account_id,
        "PORTFOLIO":str(intent.portfolio_id),
        "STRATEGY":str(strategy.pk),
        "INSTRUMENT":str(intent.instrument_id),
    }
    KillSwitch.objects.create(scope=scope,scope_id="unrelated",enabled=True)
    assert evaluate_intent(intent,{"connected":True,"reconciled":True,"mode":"paper"})[0]=="APPROVED"
    KillSwitch.objects.create(scope=scope,scope_id=matching[scope],enabled=True)
    assert evaluate_intent(intent,{"connected":True,"reconciled":True,"mode":"paper"})[0]=="REJECTED"


def test_concurrent_intents_cannot_reserve_the_same_cash(intent):
    intent.quantity=1;intent.reference_price=600;intent.save(update_fields=["quantity","reference_price"])
    second=OrderIntent.objects.create(portfolio=intent.portfolio,instrument=intent.instrument,side="BUY",quantity=1,
        reference_price=600,idempotency_key="intent-2")
    first_decision=evaluate_intent(intent,{"connected":True,"reconciled":True,"mode":"paper"})[0]
    second_decision=evaluate_intent(second,{"connected":True,"reconciled":True,"mode":"paper"})[0]
    assert first_decision=="APPROVED" and second_decision=="HELD"
    assert CapitalReservation.objects.filter(status="ACTIVE").count()==1


@pytest.mark.django_db(transaction=True)
def test_postgresql_row_locks_serialize_competing_capital_reservations(intent):
    if connection.vendor!="postgresql":pytest.skip("Row-lock concurrency is verified against PostgreSQL")
    intent.quantity=1;intent.reference_price=600;intent.save(update_fields=["quantity","reference_price"])
    second=OrderIntent.objects.create(portfolio=intent.portfolio,instrument=intent.instrument,side="BUY",quantity=1,
        reference_price=600,idempotency_key="concurrent-intent-2")
    barrier=Barrier(2)
    def evaluate(intent_id):
        close_old_connections();barrier.wait()
        try:return evaluate_intent(OrderIntent.objects.get(pk=intent_id),{"connected":True,"reconciled":True,"mode":"paper"})[0]
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        decisions=list(pool.map(evaluate,[intent.pk,second.pk]))
    assert sorted(decisions)==["APPROVED","HELD"]
    assert CapitalReservation.objects.filter(status="ACTIVE").count()==1


def test_persisted_policy_not_request_values_controls_order_limit(intent):
    intent.reference_price=10;intent.save(update_fields=["reference_price"])
    PreTradeRiskPolicy.objects.create(portfolio=intent.portfolio,maximum_order_quantity=3,maximum_order_notional=100000)
    decision,quantity,_=evaluate_intent(intent,{"connected":True,"reconciled":True,"mode":"paper"})
    assert decision=="RESIZED" and quantity==3
    reservation=CapitalReservation.objects.get(order_intent=intent)
    assert reservation.amount>Decimal("30") and reservation.estimated_fees>0
