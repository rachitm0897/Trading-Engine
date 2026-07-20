import pytest
import importlib
from django.test import override_settings
from django.urls import clear_url_caches

pytestmark = pytest.mark.django_db
def test_health_and_api_envelope(client):
    body = client.get("/healthz").json()
    assert body["ok"] and body["data"]["status"] == "healthy"
    assert body["data"]["process"] == "running" and "database" not in body["data"]
    assert set(client.get("/api/v1/system/").json()) == {"ok", "data", "error", "meta"}


def test_prefix_preserved_backend_health_api_and_dashboard_alias(client):
    import config.urls

    try:
        with override_settings(APP_BASE_PATH="/trading_eng_backend"):
            importlib.reload(config.urls)
            clear_url_caches()
            assert client.get("/trading_eng_backend/healthz").status_code == 200
            assert client.get("/trading_eng_backend/api/v1/system/").status_code == 200
            redirect = client.get("/trading_eng_backend/dashboard")
            assert redirect.status_code == 302
            assert redirect["Location"] == "/trading_eng_backend/api/v1/dashboard/summary/"
            # Prefix-stripped requests remain valid for QFS's alternate proxy mode.
            assert client.get("/healthz", HTTP_X_FORWARDED_PREFIX="/trading_eng_backend").status_code == 200
    finally:
        importlib.reload(config.urls)
        clear_url_caches()


def test_readiness_reports_missing_broker_configuration_names_only(client, settings):
    settings.BROKER_STATIC_DEVELOPMENT_GATEWAY_ENABLED = False
    settings.BROKER_SESSION_ENCRYPTION_KEY = ""
    settings.IBKR_GATEWAY_IMAGE = ""
    settings.QCH_APP_ID = ""
    settings.QCH_API_HOST = ""
    settings.QCH_SERVICE_TOKEN = ""
    result = client.get("/readyz")
    assert result.status_code == 503
    details = result.json()["error"]["details"]
    assert details["missing"] == [
        "BROKER_SESSION_ENCRYPTION_KEY",
        "IBKR_GATEWAY_IMAGE",
        "QCH_API_HOST",
        "QCH_APP_ID",
        "QCH_SERVICE_TOKEN",
    ]
    assert "qch-secret" not in result.content.decode()
