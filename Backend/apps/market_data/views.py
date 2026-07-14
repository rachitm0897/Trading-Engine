import json
import uuid

from apps.audit.models import AuditEvent
from apps.core.views import response

from .models import MarketDataProviderConfiguration
from .services import FinnhubClient, FinnhubError, encrypt_api_key, provider_status


def _is_admin(request):
    return bool(getattr(request, "user", None) and request.user.is_authenticated and request.user.is_active and request.user.is_staff)


def _admin_required(request):
    if _is_admin(request):
        return None
    return response(status=403, error={"code": "ADMIN_REQUIRED", "message": "An authenticated administrator is required", "details": {}})


def status(request):
    if request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    return response({**provider_status(), "can_manage": _is_admin(request)})


def configure(request):
    denied = _admin_required(request)
    if denied:
        return denied
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "POST required", "details": {}})
    try:
        payload = json.loads(request.body or b"{}")
        config, _ = MarketDataProviderConfiguration.objects.get_or_create(provider="FINNHUB")
        changed = []
        api_key = str(payload.get("api_key") or "").strip()
        if api_key:
            config.encrypted_api_key = encrypt_api_key(api_key)
            config.api_key_last_four = api_key[-4:]
            changed.extend(["encrypted_api_key", "api_key_last_four"])
        if "enabled" in payload:
            config.enabled = bool(payload["enabled"])
            changed.append("enabled")
        if "override_environment" in payload:
            config.override_environment = bool(payload["override_environment"])
            changed.append("override_environment")
        if not changed:
            raise ValueError("Provide an API key or a provider setting to update")
        config.updated_by = request.user.get_username()
        changed.extend(["updated_by", "updated_at"])
        config.save(update_fields=list(dict.fromkeys(changed)))
        AuditEvent.objects.create(
            event_type="market_data.credential.updated",
            actor=request.user.get_username(),
            aggregate_type="market_data_provider",
            aggregate_id="FINNHUB",
            data={"key_replaced": bool(api_key), "enabled": config.enabled, "override_environment": config.override_environment},
            idempotency_key=f"finnhub-config:{uuid.uuid4()}",
        )
        return response({**provider_status(), "can_manage": True})
    except (ValueError, json.JSONDecodeError) as exc:
        return response(status=400, error={"code": "INVALID_FINNHUB_CONFIGURATION", "message": str(exc), "details": {}})


def test(request):
    denied = _admin_required(request)
    if denied:
        return denied
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "POST required", "details": {}})
    try:
        payload = json.loads(request.body or b"{}")
        result = FinnhubClient().test_connection(str(payload.get("symbol") or "AAPL").upper())
        AuditEvent.objects.create(
            event_type="market_data.connection.tested",
            actor=request.user.get_username(),
            aggregate_type="market_data_provider",
            aggregate_id="FINNHUB",
            data={"connected": True, "source": result["source"]},
            idempotency_key=f"finnhub-test:{uuid.uuid4()}",
        )
        return response({**provider_status(), **result, "can_manage": True})
    except (FinnhubError, ValueError, json.JSONDecodeError) as exc:
        status_code = exc.status_code if isinstance(exc, FinnhubError) else 400
        AuditEvent.objects.create(
            event_type="market_data.connection.tested",
            actor=request.user.get_username(),
            aggregate_type="market_data_provider",
            aggregate_id="FINNHUB",
            data={"connected": False, "code": getattr(exc, "code", "FINNHUB_TEST_FAILED")},
            idempotency_key=f"finnhub-test:{uuid.uuid4()}",
        )
        return response(status=status_code, error={"code": getattr(exc, "code", "FINNHUB_TEST_FAILED"), "message": str(exc), "details": {}})
