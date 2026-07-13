import responses
from apps.broker_gateway.client import GatewayClient

@responses.activate
def test_gateway_auth_and_safe_retry():
    url = "http://gateway/api/v1/health/"
    responses.get(url, status=503, json={"ok":False})
    responses.get(url, status=200, json={"ok":True,"data":{"connected":True}})
    client = GatewayClient("http://gateway/api/v1", "secret")
    assert client.health()["connected"] is True
    assert responses.calls[1].request.headers["Authorization"] == "Bearer secret"

@responses.activate
def test_gateway_contract_search_waits_for_durable_command():
    responses.post("http://gateway/api/v1/contracts/search/",json={"ok":True,"data":{"command_id":7,"status":"PENDING"}},status=202)
    responses.get("http://gateway/api/v1/commands/7/",json={"ok":True,"data":{"command_id":7,"status":"COMPLETED","result":{"results":[{"symbol":"BHP","conid":123}]}}})
    results=GatewayClient("http://gateway/api/v1","secret").search_contracts("BHP")
    assert results==[{"symbol":"BHP","conid":123}]
