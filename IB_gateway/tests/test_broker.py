import pytest
from broker.base import BrokerAdapter
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
