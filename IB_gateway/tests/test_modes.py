import pytest
from django.test import override_settings

from gateway_service.modes import normalize_trading_mode, tws_port_for_mode


@pytest.mark.parametrize(("value", "mode", "port"), [
    ("paper", "paper", 4002),
    ("PAPER", "paper", 4002),
    ("live", "live", 4001),
    (" Live ", "live", 4001),
])
def test_exact_modes_select_expected_tws_port(value, mode, port):
    assert normalize_trading_mode(value) == mode
    assert tws_port_for_mode(value) == port


@pytest.mark.parametrize("value", ["", "demo", "shadow", "test", None])
def test_invalid_ibkr_mode_is_rejected(value):
    with pytest.raises(ValueError, match="paper or live"):
        normalize_trading_mode(value)


@pytest.mark.django_db
@override_settings(IBC_TRADING_MODE="live")
def test_gateway_health_returns_normalized_live_mode(client):
    result = client.get("/api/v1/health/", HTTP_AUTHORIZATION="Bearer test-token")
    assert result.status_code == 200
    assert result.json()["data"]["mode"] == "live"
