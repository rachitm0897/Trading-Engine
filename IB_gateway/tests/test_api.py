import json
import pytest
from gateway_service.models import GatewayCommand, GatewayEvent

pytestmark=pytest.mark.django_db
AUTH={"HTTP_AUTHORIZATION":"Bearer test-token"}

def test_service_authentication(client):
    assert client.get("/api/v1/health/").status_code==401
    body=client.get("/api/v1/health/",**AUTH).json()
    assert body["ok"] and "connected" in body["data"]

def test_order_command_idempotency(client):
    payload={"internal_id":"I1","symbol":"AAPL","side":"BUY","quantity":"1"}
    headers={**AUTH,"HTTP_IDEMPOTENCY_KEY":"same","content_type":"application/json"}
    first=client.post("/api/v1/orders/",json.dumps(payload),**headers).json()
    second=client.post("/api/v1/orders/",json.dumps(payload),**headers).json()
    assert first["data"]["command_id"]==second["data"]["command_id"] and GatewayCommand.objects.count()==1

def test_event_sequence_and_ack(client):
    GatewayEvent.objects.create(event_key="1",event_type="x",payload={})
    second=GatewayEvent.objects.create(event_key="2",event_type="x",payload={})
    body=client.get("/api/v1/events/?after=0",**AUTH).json()
    assert [x["id"] for x in body["data"]]==sorted(x["id"] for x in body["data"])
    client.post("/api/v1/events/ack/",json.dumps({"sequence":second.pk}),content_type="application/json",**AUTH)
    assert GatewayEvent.objects.filter(acknowledged=True).count()==2

def test_event_sequence_recovers_when_backend_cursor_is_ahead(client):
    event=GatewayEvent.objects.create(event_key="after-reset",event_type="command.qualify.completed",payload={"conid":1})
    body=client.get("/api/v1/events/?after=999999",**AUTH).json()
    assert body["meta"]["sequence_reset"] is True
    assert [row["id"] for row in body["data"]]==[event.pk]

def test_completed_orders_snapshot_endpoint(client):
    GatewayEvent.objects.create(event_key="completed",event_type="snapshot.completed_orders",payload={"value":[{"broker_order_id":"1"}]})
    body=client.get("/api/v1/completed-orders/",**AUTH).json()
    assert body["data"][0]["broker_order_id"]=="1"

def test_contract_search_and_command_detail(client):
    response=client.post("/api/v1/contracts/search/",json.dumps({"query":"BHP"}),content_type="application/json",**AUTH)
    assert response.status_code==202
    command=GatewayCommand.objects.get(pk=response.json()["data"]["command_id"])
    command.status="COMPLETED";command.result={"results":[{"symbol":"BHP","conid":123,"primary_exchange":"ASX"}]};command.save()
    detail=client.get(f"/api/v1/commands/{command.pk}/",**AUTH).json()["data"]
    assert detail["status"]=="COMPLETED" and detail["result"]["results"][0]["conid"]==123

def test_no_credential_leakage(client,settings):
    settings.IB_USERNAME="SECRET_USER"; settings.IB_PASSWORD="SECRET_PASSWORD"
    content=client.get("/api/v1/session/",**AUTH).content.decode()
    assert "SECRET_USER" not in content and "SECRET_PASSWORD" not in content
