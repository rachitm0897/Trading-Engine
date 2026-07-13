import pytest
from collections import deque
from datetime import datetime, timezone
from types import SimpleNamespace
from broker.base import BrokerAdapter
from broker.ib_async_adapter import IBAsyncBrokerAdapter
from broker.mock import MockBrokerAdapter
from gateway_service.models import GatewayCommand, GatewayEvent
from gateway_service.services import process_command

pytestmark=pytest.mark.django_db

def test_mock_implements_adapter_and_order_lifecycle():
    broker=MockBrokerAdapter(); assert isinstance(broker,BrokerAdapter)
    broker.connect(); matches=broker.search_contracts("BHP"); qualified=broker.qualify_contract(matches[0])
    placed=broker.place_order({"internal_id":"I1","symbol":"AAPL","side":"BUY","quantity":1})
    assert len(matches)==2 and matches[1]["primary_exchange"]=="ASX"
    assert qualified["qualified"] and qualified["conid"]==matches[0]["conid"] and placed["status"]=="Submitted"
    assert broker.modify_order({"internal_id":"I1","quantity":2})["quantity"]==2
    assert broker.cancel_order({"internal_id":"I1"})["status"]=="Cancelled"
    cancellation=broker.drain_order_events()[0]
    assert cancellation["broker_status"]=="Cancelled" and cancellation["operator_requested"] is True
    assert broker.refresh_state()["accounts"] == []

def test_command_processing_persists_callback():
    broker=MockBrokerAdapter(); broker.connect()
    command=GatewayCommand.objects.create(command_type="PLACE_ORDER",idempotency_key="k",payload={"internal_id":"I1","symbol":"AAPL","side":"BUY","quantity":1})
    process_command(command,broker); command.refresh_from_db()
    assert command.status=="COMPLETED" and GatewayEvent.objects.count()==1

def test_search_command_returns_multiple_exact_contracts():
    broker=MockBrokerAdapter();broker.connect()
    command=GatewayCommand.objects.create(command_type="SEARCH_CONTRACTS",idempotency_key="search:BHP",payload={"query":"BHP"})
    process_command(command,broker);command.refresh_from_db()
    assert command.status=="COMPLETED" and len(command.result["results"])==2

def test_market_subscription_commands_are_idempotent():
    broker=MockBrokerAdapter();broker.connect();payload={"subscription_key":"1:1m","instrument_id":1,"conid":123,
        "symbol":"AAPL","timeframe":"1m","historical_bars":20}
    first=GatewayCommand.objects.create(command_type="SUBSCRIBE_MARKET_DATA",idempotency_key="sub:1",payload=payload)
    process_command(first,broker)
    assert first.result["state"]=="ACTIVE" and len(broker.subscriptions)==1
    cancel=GatewayCommand.objects.create(command_type="CANCEL_MARKET_DATA",idempotency_key="cancel:1",payload={"subscription_key":"1:1m"})
    process_command(cancel,broker)
    assert cancel.result["state"]=="INACTIVE" and not broker.subscriptions

def test_kill_switch_blocks_submission():
    broker=MockBrokerAdapter(); broker.connect(); broker.killed=True
    with pytest.raises(RuntimeError): broker.place_order({"internal_id":"I1"})

def test_ibkr_order_event_preserves_exact_rejection_diagnostics():
    adapter=IBAsyncBrokerAdapter.__new__(IBAsyncBrokerAdapter);adapter.operator_cancellations=set()
    contract=SimpleNamespace(conId=265598,symbol="AAPL",localSymbol="AAPL",secType="STK",exchange="SMART",
        primaryExchange="NASDAQ",currency="USD")
    order=SimpleNamespace(orderRef="internal-1",account="DU1",orderId=881,permId=9901)
    status=SimpleNamespace(status="Inactive",whyHeld="locate pending")
    log=SimpleNamespace(time=datetime(2026,7,13,1,0,tzinfo=timezone.utc),status="Inactive",
        message="Order rejected - insufficient equity",errorCode=201)
    trade=SimpleNamespace(order=order,orderStatus=status,contract=contract,log=[log],advancedError='{"errorCode":201}')
    event=adapter._order_event(trade)
    assert event["error_code"]=="201" and event["error_message"]=="Order rejected - insufficient equity"
    assert event["why_held"]=="locate pending" and event["advanced_reject"]=={"errorCode":201}
    assert event["trade_log"][0]["status"]=="Inactive" and event["occurred_at"]=="2026-07-13T01:00:00+00:00"

def test_ibkr_async_market_error_retains_exact_permission_reason():
    adapter=IBAsyncBrokerAdapter.__new__(IBAsyncBrokerAdapter)
    adapter.ib=SimpleNamespace(trades=lambda:[]);adapter.order_events=deque();adapter.market_events=deque()
    adapter.recent_errors=deque(maxlen=50);adapter.market_subscriptions={"5:1m":{"request_id":42}};adapter.market_request_ids={42:{"subscription_key":"5:1m",
        "instrument_id":5,"conid":265598,"symbol":"AAPL","timeframe":"1m"}}
    adapter._on_error(42,354,"Requested market data is not subscribed",SimpleNamespace(conId=265598))
    event=adapter.drain_market_events()[0]
    assert event["event_kind"]=="ERROR" and event["error_code"]=="354"
    assert event["error_message"]=="Requested market data is not subscribed" and event["subscription_key"]=="5:1m"
    assert not adapter.market_request_ids and not adapter.market_subscriptions
