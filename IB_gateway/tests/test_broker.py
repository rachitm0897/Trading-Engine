import pytest
from broker.base import BrokerAdapter
from broker.mock import MockBrokerAdapter
from gateway_service.models import GatewayCommand, GatewayEvent
from gateway_service.services import process_command

pytestmark=pytest.mark.django_db

def test_mock_implements_adapter_and_order_lifecycle():
    broker=MockBrokerAdapter(); assert isinstance(broker,BrokerAdapter)
    broker.connect(); qualified=broker.qualify_contract({"symbol":"AAPL"})
    placed=broker.place_order({"internal_id":"I1","symbol":"AAPL","side":"BUY","quantity":1})
    assert qualified["qualified"] and placed["status"]=="Submitted"
    assert broker.modify_order({"internal_id":"I1","quantity":2})["quantity"]==2
    assert broker.cancel_order({"internal_id":"I1"})["status"]=="Cancelled"
    assert broker.refresh_state()["accounts"] == []

def test_command_processing_persists_callback():
    broker=MockBrokerAdapter(); broker.connect()
    command=GatewayCommand.objects.create(command_type="PLACE_ORDER",idempotency_key="k",payload={"internal_id":"I1","symbol":"AAPL","side":"BUY","quantity":1})
    process_command(command,broker); command.refresh_from_db()
    assert command.status=="COMPLETED" and GatewayEvent.objects.count()==1

def test_kill_switch_blocks_submission():
    broker=MockBrokerAdapter(); broker.connect(); broker.killed=True
    with pytest.raises(RuntimeError): broker.place_order({"internal_id":"I1"})
