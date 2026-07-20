import pytest
import importlib
from pathlib import Path
from django.test import override_settings
from django.urls import clear_url_caches

pytestmark=pytest.mark.django_db
def test_public_health(client): assert client.get("/healthz").json()["data"]["status"]=="healthy"


def test_prefix_preserved_and_stripped_gateway_routes(client):
    import config.urls

    try:
        with override_settings(APP_BASE_PATH="/trading_eng_gateway"):
            importlib.reload(config.urls)
            clear_url_caches()
            assert client.get("/trading_eng_gateway/healthz").status_code == 200
            auth = {"HTTP_AUTHORIZATION": "Bearer test-token"}
            assert client.get("/trading_eng_gateway/api/v1/health/", **auth).status_code == 200
            assert client.get("/api/v1/session/", HTTP_X_FORWARDED_PREFIX="/trading_eng_gateway", **auth).status_code == 200
    finally:
        importlib.reload(config.urls)
        clear_url_caches()


def test_public_nginx_contract_and_spelling():
    root = Path(__file__).resolve().parents[1]
    nginx = (root / "nginx.conf.template").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    combined = nginx + dockerfile
    assert "APP_BASE_PATH=/trading_eng_gateway" in dockerfile
    assert "/novnc/websockify" in nginx and "/novnc/(.*)" in nginx
    assert '"service":"ibkr-gateway"' in nginx
    assert ("tra" + "gin_eng_gateway") not in combined
