import json

import pytest
import responses
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

from apps.market_data.models import MarketDataProviderConfiguration
from apps.market_data.services import FinnhubClient, decrypt_api_key, effective_api_key, encrypt_api_key, provider_status


pytestmark = pytest.mark.django_db


@override_settings(FINNHUB_ENCRYPTION_KEY="unit-test-encryption-secret", FINNHUB_API_KEY="env-secret")
def test_key_encryption_masking_and_environment_precedence():
    encrypted = encrypt_api_key("database-secret")
    assert encrypted != "database-secret"
    assert decrypt_api_key(encrypted) == "database-secret"
    MarketDataProviderConfiguration.objects.create(
        encrypted_api_key=encrypted,
        api_key_last_four="cret",
        override_environment=True,
    )
    key, source, _ = effective_api_key()
    assert (key, source) == ("env-secret", "ENVIRONMENT")
    status = provider_status()
    assert status["masked_api_key"] == "••••cret"
    assert "env-secret" not in json.dumps(status, default=str)
    assert "database-secret" not in json.dumps(status, default=str)


@override_settings(
    FINNHUB_ENCRYPTION_KEY="unit-test-encryption-secret",
    FINNHUB_API_KEY="env-secret",
    FINNHUB_API_KEY_OVERRIDE_ENABLED=True,
)
def test_explicit_database_override_requires_server_permission():
    MarketDataProviderConfiguration.objects.create(
        encrypted_api_key=encrypt_api_key("database-secret"),
        api_key_last_four="cret",
        override_environment=True,
    )
    key, source, _ = effective_api_key()
    assert (key, source) == ("database-secret", "DATABASE")


@responses.activate
@override_settings(FINNHUB_API_KEY="test-key", FINNHUB_MAX_RETRIES=1)
def test_finnhub_client_uses_secret_header_and_handles_rate_limit_retry():
    responses.add(responses.GET, "https://finnhub.io/api/v1/quote", status=429, json={"error": "limit"})
    responses.add(responses.GET, "https://finnhub.io/api/v1/quote", status=200, json={"c": 123.45})
    result = FinnhubClient().test_connection("AAPL")
    assert result["connected"] is True
    assert len(responses.calls) == 2
    assert responses.calls[-1].request.headers["X-Finnhub-Token"] == "test-key"
    assert "test-key" not in responses.calls[-1].request.url


@override_settings(FINNHUB_ENCRYPTION_KEY="unit-test-encryption-secret", FINNHUB_API_KEY="")
def test_finnhub_configuration_endpoint_is_admin_only_and_never_returns_secret(client):
    denied = client.post(
        "/api/v1/data-providers/finnhub/configure/",
        data=json.dumps({"api_key": "browser-submitted-secret"}),
        content_type="application/json",
    )
    assert denied.status_code == 403
    admin = get_user_model().objects.create_user(username="admin", password="password", is_staff=True)
    client.force_login(admin)
    saved = client.post(
        "/api/v1/data-providers/finnhub/configure/",
        data=json.dumps({"api_key": "browser-submitted-secret", "enabled": True}),
        content_type="application/json",
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["data"]["masked_api_key"] == "••••cret"
    assert "browser-submitted-secret" not in saved.content.decode()
    stored = MarketDataProviderConfiguration.objects.get()
    assert stored.encrypted_api_key != "browser-submitted-secret"


@override_settings(FINNHUB_ENCRYPTION_KEY="unit-test-encryption-secret", FINNHUB_API_KEY="")
def test_staff_session_and_csrf_are_required_for_browser_credential_changes():
    get_user_model().objects.create_user(username="operator", password="password", is_staff=True)
    browser = Client(enforce_csrf_checks=True)
    browser.get("/api/v1/system/")
    token = browser.cookies["csrftoken"].value
    blocked = browser.post(
        "/api/v1/auth/session/",
        data=json.dumps({"username": "operator", "password": "password"}),
        content_type="application/json",
    )
    assert blocked.status_code == 403
    authenticated = browser.post(
        "/api/v1/auth/session/",
        data=json.dumps({"username": "operator", "password": "password"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    assert authenticated.status_code == 200
    rotated = browser.cookies["csrftoken"].value
    saved = browser.post(
        "/api/v1/data-providers/finnhub/configure/",
        data=json.dumps({"api_key": "csrf-protected-secret"}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=rotated,
    )
    assert saved.status_code == 200
