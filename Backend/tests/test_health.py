import pytest
pytestmark = pytest.mark.django_db
def test_health_and_api_envelope(client):
    body = client.get("/healthz").json()
    assert body["ok"] and body["data"]["status"] == "healthy"
    assert set(client.get("/api/v1/system/").json()) == {"ok", "data", "error", "meta"}

