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

