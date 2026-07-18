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


@responses.activate
def test_gateway_contract_search_replays_completed_command_result():
    responses.post("http://gateway/api/v1/contracts/search/",json={"ok":True,"data":{"command_id":7,"status":"COMPLETED"}},status=202)
    responses.get("http://gateway/api/v1/commands/7/",json={"ok":True,"data":{"command_id":7,"status":"COMPLETED","result":{"results":[{"symbol":"AAPL","conid":265598}]}}})
    results=GatewayClient("http://gateway/api/v1","secret").search_contracts("AAPL")
    assert results==[{"symbol":"AAPL","conid":265598}]


@responses.activate
def test_gateway_daily_history_uses_authenticated_durable_read_only_command():
    payload={"conid":265598,"symbol":"AAPL","exchange":"SMART","currency":"USD","bar_size":"1 day",
             "duration":"5 Y","what_to_show":"ADJUSTED_LAST","use_rth":True,"end_time":""}
    responses.post("http://gateway/api/v1/market-data/history/",
                   json={"ok":True,"data":{"command_id":9,"status":"PENDING"}},status=202)
    responses.get("http://gateway/api/v1/commands/9/",json={"ok":True,"data":{
        "command_id":9,"status":"COMPLETED","result":{"provider":"IBKR","bars":[{"date":"2026-01-02","close":"100"}]}}})
    result=GatewayClient("http://gateway/api/v1","secret").historical_bars(payload)
    assert result["provider"]=="IBKR" and result["bars"][0]["close"]=="100"
    assert responses.calls[0].request.headers["Authorization"]=="Bearer secret"
