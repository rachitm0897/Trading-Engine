import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import responses
import pytest
from django.db import close_old_connections, connection
from django.test import Client
from apps.accounts.models import BrokerAccount
from apps.instruments.models import Instrument
from apps.oms.models import Order, OrderIntent
from apps.portfolios.models import TradingPortfolio
from tests.managed_gateway import bind_managed_gateway

pytestmark=pytest.mark.django_db

@responses.activate
def test_manual_order_runs_risk_then_queues_gateway_command(client, settings):
    account=BrokerAccount.objects.create(account_id="DU1",available_cash=10000,is_reconciled=True)
    portfolio=TradingPortfolio.objects.create(name="Paper",account=account)
    session=bind_managed_gateway(portfolio, settings)
    instrument=Instrument.objects.create(symbol="AAPL")
    responses.get(f"{session.internal_base_url}/health/",json={"ok":True,"data":{"connected":True,"reconciled":True,"mode":"paper"},"error":None,"meta":{}})
    responses.post(f"{session.internal_base_url}/orders/",status=202,json={"ok":True,"data":{"command_id":1,"status":"PENDING"},"error":None,"meta":{}})
    payload={"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,"side":"BUY","order_type":"MKT","quantity":"5","reference_price":"100","time_in_force":"DAY"}
    result=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="manual-1")
    assert result.status_code==201 and result.json()["data"]["status"]=="QUEUED"
    duplicate=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="manual-1")
    assert duplicate.status_code==200 and duplicate.json()["data"]["internal_id"]==result.json()["data"]["internal_id"]

def test_manual_order_requires_idempotency_key(client):
    assert client.post("/api/v1/orders/",data="{}",content_type="application/json").status_code==400


@responses.activate
def test_manual_order_rejects_same_key_with_different_request(client, settings):
    account=BrokerAccount.objects.create(account_id="DU1",available_cash=10000,is_reconciled=True)
    portfolio=TradingPortfolio.objects.create(name="Paper",account=account)
    session=bind_managed_gateway(portfolio, settings)
    instrument=Instrument.objects.create(symbol="AAPL")
    responses.get(f"{session.internal_base_url}/health/",json={"ok":True,"data":{"connected":True,"reconciled":True,"mode":"paper"},"error":None,"meta":{}})
    responses.post(f"{session.internal_base_url}/orders/",status=202,json={"ok":True,"data":{"command_id":1,"status":"PENDING"},"error":None,"meta":{}})
    payload={"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,"side":"BUY","order_type":"MKT","quantity":"5","reference_price":"100","time_in_force":"DAY"}
    assert client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="manual-conflict").status_code==201
    payload["quantity"]="6"
    conflict=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="manual-conflict")
    assert conflict.status_code==409 and conflict.json()["error"]["code"]=="IDEMPOTENCY_CONFLICT"


def test_manual_order_calls_gateway_outside_database_transactions(client,monkeypatch,settings):
    account=BrokerAccount.objects.create(account_id="DU1",available_cash=10000,is_reconciled=True)
    portfolio=TradingPortfolio.objects.create(name="Paper",account=account)
    bind_managed_gateway(portfolio, settings)
    instrument=Instrument.objects.create(symbol="AAPL")
    from apps.broker_gateway.client import GatewayClient
    baseline_atomic_depth=len(connection.atomic_blocks)
    def health(self):
        assert len(connection.atomic_blocks)==baseline_atomic_depth
        return {"connected":True,"reconciled":True,"mode":"paper"}
    def place(self,payload,key):
        assert len(connection.atomic_blocks)==baseline_atomic_depth
        return {"command_id":1,"status":"PENDING"}
    monkeypatch.setattr(GatewayClient,"health",health)
    monkeypatch.setattr(GatewayClient,"place_order",place)
    payload={"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,"side":"BUY","order_type":"MKT","quantity":"5","reference_price":"100","time_in_force":"DAY"}
    assert client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="outside-tx").status_code==201


def test_manual_order_persists_command_without_calling_gateway(client,monkeypatch,settings):
    account=BrokerAccount.objects.create(account_id="DU1",available_cash=10000,is_reconciled=True)
    portfolio=TradingPortfolio.objects.create(name="Paper",account=account)
    bind_managed_gateway(portfolio, settings)
    instrument=Instrument.objects.create(symbol="AAPL")
    from apps.broker_gateway.client import GatewayClient
    monkeypatch.setattr(GatewayClient,"health",lambda self:{"connected":True,"reconciled":True,"mode":"paper"})
    calls={"count":0}
    def place(self,payload,key):
        calls["count"]+=1
        return {"command_id":1,"status":"PENDING"}
    monkeypatch.setattr(GatewayClient,"place_order",place)
    payload={"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,"side":"BUY","order_type":"MKT","quantity":"5","reference_price":"100","time_in_force":"DAY"}
    first=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="retry-order")
    stored=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="retry-order")
    assert first.status_code==201 and stored.status_code==200
    assert calls["count"]==0
    assert first.json()["data"]["broker_command"]["status"]=="PENDING"


def _manual_order_case():
    account=BrokerAccount.objects.create(account_id="DU-VALIDATE",available_cash=10000,is_reconciled=True)
    portfolio=TradingPortfolio.objects.create(name="Validation",account=account)
    instrument=Instrument.objects.create(symbol="VALID")
    return portfolio,instrument


@pytest.mark.parametrize("changes",[
    {"quantity":"0"},
    {"quantity":"1.000000001"},
    {"side":"HOLD"},
    {"order_type":"LMT"},
    {"order_type":"STP"},
    {"order_type":"MKT","limit_price":"10"},
    {"time_in_force":"IOC"},
    {"unexpected":True},
])
def test_manual_order_rejects_invalid_payloads_before_gateway(client,changes):
    portfolio,instrument=_manual_order_case()
    payload={"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,"side":"BUY",
        "order_type":"MKT","quantity":"1","reference_price":"10","time_in_force":"DAY"}
    payload.update(changes)
    result=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="invalid-manual-order")
    assert result.status_code==400
    assert result.json()["error"]["code"]=="INVALID_ORDER"
    assert OrderIntent.objects.count()==0


def test_manual_order_requires_active_tradable_instrument(client):
    portfolio,instrument=_manual_order_case();instrument.tradable=False;instrument.save(update_fields=["tradable"])
    payload={"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,"side":"BUY","quantity":"1","reference_price":"10"}
    result=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="inactive-instrument")
    assert result.status_code==400
    assert "active and tradable" in result.json()["error"]["message"]


def test_manual_order_rejects_non_object_json_and_wrong_method(client):
    invalid=client.post("/api/v1/orders/","[]",content_type="application/json",HTTP_IDEMPOTENCY_KEY="json-array")
    assert invalid.status_code==400 and invalid.json()["error"]["code"]=="INVALID_ORDER"
    assert client.put("/api/v1/orders/",data="{}",content_type="application/json").status_code==405


@pytest.mark.parametrize("changes",[
    {"quantity":"1"},
    {"quantity":"3.000000001"},
    {"limit_price":"10"},
    {"side":"SELL"},
])
def test_order_modify_rejects_unsafe_fields_and_values(client,changes):
    portfolio,instrument=_manual_order_case()
    intent=OrderIntent.objects.create(portfolio=portfolio,instrument=instrument,side="BUY",quantity=5,
        order_type="MKT",idempotency_key="modify-intent")
    order=Order.objects.create(intent=intent,internal_id="modify-order",status="PARTIALLY_FILLED",quantity=5,filled_quantity=2)
    result=client.patch(f"/api/v1/orders/{order.internal_id}/",json.dumps(changes),content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="modify-validation")
    assert result.status_code==400
    assert result.json()["error"]["code"]=="INVALID_ORDER"


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_manual_order_requests_submit_once(monkeypatch, settings):
    if connection.vendor!="postgresql":pytest.skip("Row-lock concurrency is verified against PostgreSQL")
    portfolio,instrument=_manual_order_case()
    bind_managed_gateway(portfolio, settings)
    from apps.broker_gateway.client import GatewayClient
    barrier=Barrier(2);lock=Lock();calls={"place":0}
    monkeypatch.setattr(GatewayClient,"health",lambda self:{"connected":True,"reconciled":True,"mode":"paper"})
    def place(self,payload,key):
        with lock:calls["place"]+=1
        return {"command_id":1,"status":"PENDING"}
    monkeypatch.setattr(GatewayClient,"place_order",place)
    payload={"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,"side":"BUY","quantity":"1","reference_price":"10"}
    def submit():
        close_old_connections();barrier.wait()
        try:
            result=Client().post("/api/v1/orders/",json.dumps(payload),content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="concurrent-manual-order")
            return result.status_code
        finally:close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses=list(pool.map(lambda _value:submit(),range(2)))
    assert all(status in {200,201,202} for status in statuses)
    from apps.execution.models import BrokerCommand
    assert calls["place"]==0 and OrderIntent.objects.count()==1 and Order.objects.count()==1
    assert BrokerCommand.objects.count()==1
