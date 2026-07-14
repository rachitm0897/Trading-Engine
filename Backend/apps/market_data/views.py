import json
import uuid

from django.conf import settings

from apps.audit.models import AuditEvent
from apps.core.throttling import throttle_response
from apps.core.views import response

from .models import MarketDataProviderConfiguration
from .services import FinnhubClient, FinnhubError, encrypt_api_key, provider_status


def _actor(request):
    user = getattr(request, "user", None)
    return user.get_username() if user and user.is_authenticated else "operator/system"


def status(request):
    if request.method != "GET":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET required", "details": {}})
    return response(provider_status())


def configure(request):
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "POST required", "details": {}})
    throttled = throttle_response(
        request,
        "finnhub",
        limit=settings.FINNHUB_OPERATION_THROTTLE_LIMIT,
        window_seconds=settings.EXPENSIVE_OPERATION_THROTTLE_WINDOW_SECONDS,
    )
    if throttled:
        return throttled
    try:
        payload = json.loads(request.body or b"{}")
        api_key = str(payload.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("Finnhub API key cannot be empty")
        config, _ = MarketDataProviderConfiguration.objects.get_or_create(provider="FINNHUB")
        config.encrypted_api_key = encrypt_api_key(api_key)
        config.api_key_last_four = api_key[-4:]
        config.enabled = True
        config.updated_by = _actor(request)
        config.save(update_fields=["encrypted_api_key", "api_key_last_four", "enabled", "updated_by", "updated_at"])
        AuditEvent.objects.get_or_create(
            idempotency_key=f"finnhub-config:{request.headers.get('Idempotency-Key') or uuid.uuid4()}",
            defaults={
                "event_type": "market_data.credential.updated",
                "actor": _actor(request),
                "aggregate_type": "market_data_provider",
                "aggregate_id": "FINNHUB",
                "data": {"key_replaced": True, "enabled": config.enabled, "override_environment": config.override_environment},
            },
        )
        return response(provider_status())
    except (ValueError, json.JSONDecodeError) as exc:
        return response(status=400, error={"code": "INVALID_FINNHUB_CONFIGURATION", "message": str(exc), "details": {}})


def test(request):
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "POST required", "details": {}})
    throttled = throttle_response(
        request,
        "finnhub",
        limit=settings.FINNHUB_OPERATION_THROTTLE_LIMIT,
        window_seconds=settings.EXPENSIVE_OPERATION_THROTTLE_WINDOW_SECONDS,
    )
    if throttled:
        return throttled
    try:
        payload = json.loads(request.body or b"{}")
        api_key = str(payload.get("api_key") or "").strip()
        result = FinnhubClient(api_key=api_key or None).test_connection(str(payload.get("symbol") or "AAPL").upper())
        AuditEvent.objects.get_or_create(
            idempotency_key=f"finnhub-test:{request.headers.get('Idempotency-Key') or uuid.uuid4()}",
            defaults={
                "event_type": "market_data.connection.tested",
                "actor": _actor(request),
                "aggregate_type": "market_data_provider",
                "aggregate_id": "FINNHUB",
                "data": {"connected": True, "source": result["source"]},
            },
        )
        return response({**provider_status(), **result})
    except (FinnhubError, ValueError, json.JSONDecodeError) as exc:
        status_code = exc.status_code if isinstance(exc, FinnhubError) else 400
        AuditEvent.objects.get_or_create(
            idempotency_key=f"finnhub-test:{request.headers.get('Idempotency-Key') or uuid.uuid4()}",
            defaults={
                "event_type": "market_data.connection.tested",
                "actor": _actor(request),
                "aggregate_type": "market_data_provider",
                "aggregate_id": "FINNHUB",
                "data": {"connected": False, "code": getattr(exc, "code", "FINNHUB_TEST_FAILED")},
            },
        )
        return response(status=status_code, error={"code": getattr(exc, "code", "FINNHUB_TEST_FAILED"), "message": str(exc), "details": {}})
