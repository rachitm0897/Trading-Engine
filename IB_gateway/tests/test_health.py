import pytest
pytestmark=pytest.mark.django_db
def test_public_health(client): assert client.get("/healthz").json()["data"]["status"]=="healthy"

