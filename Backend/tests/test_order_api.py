import json
import responses
import pytest
from apps.accounts.models import BrokerAccount
from apps.instruments.models import Instrument
from apps.portfolios.models import TradingPortfolio

pytestmark=pytest.mark.django_db

@responses.activate
def test_manual_order_runs_risk_then_queues_gateway_command(client):
    account=BrokerAccount.objects.create(account_id="DU1",available_cash=10000,is_reconciled=True)
    portfolio=TradingPortfolio.objects.create(name="Paper",account=account)
    instrument=Instrument.objects.create(symbol="AAPL")
    responses.get("http://localhost:8080/api/v1/health/",json={"ok":True,"data":{"connected":True,"reconciled":True,"mode":"paper"},"error":None,"meta":{}})
    responses.post("http://localhost:8080/api/v1/orders/",status=202,json={"ok":True,"data":{"command_id":1,"status":"PENDING"},"error":None,"meta":{}})
    payload={"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,"side":"BUY","order_type":"MKT","quantity":"5","reference_price":"100","time_in_force":"DAY"}
    result=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="manual-1")
    assert result.status_code==201 and result.json()["data"]["status"]=="QUEUED"
    duplicate=client.post("/api/v1/orders/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="manual-1")
    assert duplicate.status_code==200 and duplicate.json()["data"]["internal_id"]==result.json()["data"]["internal_id"]

def test_manual_order_requires_idempotency_key(client):
    assert client.post("/api/v1/orders/",data="{}",content_type="application/json").status_code==400
