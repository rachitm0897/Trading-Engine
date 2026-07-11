import json
import pytest
from django.test import override_settings
from apps.accounts.models import BrokerAccount
from apps.instruments.models import Instrument
from apps.portfolios.models import TradingPortfolio

pytestmark=pytest.mark.django_db


@pytest.fixture
def portfolio():
    account=BrokerAccount.objects.create(account_id="DU-API",net_liquidation=10000,available_cash=5000)
    return TradingPortfolio.objects.create(name="API",account=account)


@override_settings(KAFKA_ENABLED=False,FLINK_REST_URL="http://127.0.0.1:1")
def test_streaming_health_topics_and_metrics(client):
    assert client.get("/api/v1/streaming/health/").status_code==200
    assert client.get("/api/v1/streaming/topics/").json()["data"]
    assert client.get("/api/v1/streaming/dead-letter/").status_code==200
    assert client.get("/metrics").status_code==200


def test_flow_api_requires_key_and_is_idempotent(client,portfolio):
    payload={"portfolio_id":portfolio.pk,"flow_type":"DEPOSIT","amount":"100"}
    assert client.post("/api/v1/allocations/flows/",json.dumps(payload),content_type="application/json").status_code==400
    first=client.post("/api/v1/allocations/flows/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="flow-api")
    second=client.post("/api/v1/allocations/flows/",json.dumps(payload),content_type="application/json",HTTP_IDEMPOTENCY_KEY="flow-api")
    assert first.status_code==201 and second.json()["data"]["id"]==first.json()["data"]["id"]


def test_rebalance_preview_and_sizing_preview_never_create_orders(client,portfolio):
    instrument=Instrument.objects.create(symbol="API")
    rebalance=client.post("/api/v1/rebalancing/preview/",json.dumps({"portfolio_id":portfolio.pk,"prices":{str(instrument.pk):"10"}}),
        content_type="application/json",HTTP_IDEMPOTENCY_KEY="preview-api")
    assert rebalance.status_code==201 and rebalance.json()["data"]["mode"]=="SHADOW"
    sizing=client.post("/api/v1/position-sizing/preview/",json.dumps({"portfolio_id":portfolio.pk,"instrument_id":instrument.pk,
        "target_quantity":"10","entry_price":"10","stop_price":"9","adv":"10000"}),content_type="application/json",HTTP_IDEMPOTENCY_KEY="size-api")
    assert sizing.status_code==201 and "binding_constraint" in sizing.json()["data"]
    from apps.oms.models import Order,OrderIntent
    assert not Order.objects.exists() and not OrderIntent.objects.exists()
