import json

import pytest
import responses

from apps.accounts.models import BrokerAccount
from apps.broker_gateway.sync import process_snapshot
from apps.instruments.models import Instrument
from apps.oms.models import OrderIntent
from apps.oms.services import create_order, transition
from apps.portfolios.models import TradingPortfolio


pytestmark = pytest.mark.django_db


@pytest.fixture
def submitted_order():
    account = BrokerAccount.objects.create(account_id="DU-DIAGNOSTICS", is_reconciled=True)
    portfolio = TradingPortfolio.objects.create(name="Diagnostics paper", account=account)
    instrument = Instrument.objects.create(symbol="AAPL", exchange="SMART", primary_exchange="NASDAQ")
    intent = OrderIntent.objects.create(portfolio=portfolio, instrument=instrument, side="BUY", quantity=1,
        idempotency_key="diagnostic-intent")
    order = create_order(intent)
    order = transition(order, "QUEUED", "oms", "diagnostic:queued")
    return transition(order, "SUBMITTED", "gateway", "diagnostic:submitted")


def test_exact_ibkr_rejection_is_append_only_and_changes_status(submitted_order):
    payload = {"source_event_id":"reject-201","internal_id":submitted_order.internal_id,"account":"DU-DIAGNOSTICS",
        "broker_order_id":"881","permanent_id":"9901","broker_status":"Inactive","error_code":"201",
        "error_message":"Order rejected - insufficient available equity","why_held":"locate pending",
        "warning_text":"Margin check failed","advanced_reject":{"errorCode":201,"errorMsg":"insufficient equity"},
        "trade_log":[{"time":"2026-07-13T01:00:00+00:00","status":"Inactive","message":"Margin check failed","error_code":"201"}],
        "occurred_at":"2026-07-13T01:00:00+00:00","operator_requested":False}
    process_snapshot({"event_type":"broker.order","payload":payload})
    process_snapshot({"event_type":"broker.order","payload":payload})
    submitted_order.refresh_from_db()
    history=submitted_order.status_history.get(event_key="broker-order:reject-201")
    assert submitted_order.status=="REJECTED" and history.reason_code=="201"
    assert history.reason=="Order rejected - insufficient available equity"
    assert history.broker_status=="Inactive" and history.details["why_held"]=="locate pending"
    assert submitted_order.status_history.filter(event_key="broker-order:reject-201").count()==1


@responses.activate
def test_operator_request_and_ibkr_cancel_confirmation_remain_distinct(client, submitted_order):
    responses.post("http://localhost:8080/api/v1/orders/%s/cancel/" % submitted_order.internal_id,status=202,
        json={"ok":True,"data":{"command_id":7,"status":"PENDING"},"error":None,"meta":{}})
    response=client.post(f"/api/v1/orders/{submitted_order.internal_id}/cancel/",json.dumps({"reason":"Operator risk review"}),
        content_type="application/json",HTTP_IDEMPOTENCY_KEY="cancel-diagnostic")
    assert response.status_code==202
    process_snapshot({"event_type":"broker.order","payload":{"source_event_id":"cancel-881",
        "internal_id":submitted_order.internal_id,"broker_order_id":"881","broker_status":"Cancelled",
        "error_code":"202","error_message":"Order cancelled - reason: exchange closed","occurred_at":"2026-07-13T02:00:00+00:00",
        "operator_requested":True}})
    submitted_order.refresh_from_db()
    operator=submitted_order.status_history.get(reason_code="OPERATOR_CANCEL_REQUEST")
    broker=submitted_order.status_history.get(reason_code="202")
    assert submitted_order.status=="CANCELLED"
    assert operator.source=="operator" and operator.reason=="Operator risk review" and operator.operator_requested
    assert broker.source=="ibkr" and broker.reason=="Order cancelled - reason: exchange closed" and broker.operator_requested


def test_order_detail_returns_chronological_exact_diagnostics(client, submitted_order):
    process_snapshot({"event_type":"broker.order","payload":{"source_event_id":"detail-reject",
        "internal_id":submitted_order.internal_id,"broker_status":"Inactive","error_code":"321",
        "error_message":"Error validating request","occurred_at":"2026-07-13T03:00:00+00:00","operator_requested":False}})
    response=client.get(f"/api/v1/orders/{submitted_order.internal_id}/detail/")
    assert response.status_code==200
    data=response.json()["data"]
    assert data["order"]["internal_id"]==submitted_order.internal_id
    assert [row["occurred_at"] for row in data["status_history"]]==sorted(row["occurred_at"] for row in data["status_history"])
    diagnostic=next(row for row in data["broker_diagnostics"] if row["reason_code"]=="321")
    assert diagnostic["reason"]=="Error validating request"
    assert set(data)=={"order","status_history","broker_diagnostics","risk_decisions","fills","strategy_attribution"}
