import base64
import hashlib
import time
from datetime import datetime, time as day_time, timezone as dt_timezone
from decimal import Decimal

import requests
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import InstrumentPriceHistory, MarketDataFetchRun, MarketDataProviderConfiguration


class FinnhubError(RuntimeError):
    def __init__(self, message, *, code="FINNHUB_ERROR", status_code=503, retryable=False):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


def _fernet():
    secret = settings.FINNHUB_ENCRYPTION_KEY or settings.SECRET_KEY
    try:
        return Fernet(secret.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
        return Fernet(derived)


def encrypt_api_key(api_key):
    value = str(api_key or "").strip()
    if not value:
        raise ValueError("Finnhub API key cannot be empty")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted_api_key):
    try:
        return _fernet().decrypt(encrypted_api_key.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise FinnhubError("Stored Finnhub credential cannot be decrypted", code="FINNHUB_CREDENTIAL_INVALID") from exc


def effective_api_key():
    config = MarketDataProviderConfiguration.objects.filter(provider="FINNHUB").first()
    environment_key = settings.FINNHUB_API_KEY.strip()
    if config and not config.enabled:
        raise FinnhubError("Finnhub provider is disabled", code="FINNHUB_DISABLED", status_code=400)
    database_allowed = bool(
        config
        and config.enabled
        and config.encrypted_api_key
        and (
            not environment_key
            or (settings.FINNHUB_API_KEY_OVERRIDE_ENABLED and config.override_environment)
        )
    )
    if database_allowed:
        return decrypt_api_key(config.encrypted_api_key), "DATABASE", config
    if environment_key:
        return environment_key, "ENVIRONMENT", config
    if config and config.enabled and config.encrypted_api_key:
        return decrypt_api_key(config.encrypted_api_key), "DATABASE", config
    raise FinnhubError("Finnhub API key is not configured", code="FINNHUB_NOT_CONFIGURED", status_code=400)


def provider_status():
    config = MarketDataProviderConfiguration.objects.filter(provider="FINNHUB").first()
    environment_key = bool(settings.FINNHUB_API_KEY.strip())
    database_key = bool(config and config.encrypted_api_key)
    database_override_active = bool(
        environment_key
        and database_key
        and config.enabled
        and config.override_environment
        and settings.FINNHUB_API_KEY_OVERRIDE_ENABLED
    )
    if config and not config.enabled:
        source = "NONE"
    else:
        source = "DATABASE" if database_key and (not environment_key or database_override_active) else "ENVIRONMENT" if environment_key else "NONE"
    last_four = settings.FINNHUB_API_KEY[-4:] if source == "ENVIRONMENT" and environment_key else config.api_key_last_four if config and database_key else ""
    return {
        "provider": "FINNHUB",
        "configured": environment_key or database_key,
        "enabled": config.enabled if config else True,
        "effective_source": source,
        "environment_configured": environment_key,
        "database_configured": database_key,
        "database_override_requested": config.override_environment if config else False,
        "database_override_allowed": settings.FINNHUB_API_KEY_OVERRIDE_ENABLED,
        "database_override_active": database_override_active,
        "masked_api_key": f"••••{last_four}" if last_four else "",
        "last_success_at": config.last_success_at if config else None,
        "last_tested_at": config.last_tested_at if config else None,
        "last_error": config.last_error if config else "",
        "rate_limit_state": config.rate_limit_state if config else {},
        "updated_at": config.updated_at if config else None,
    }


class FinnhubClient:
    def __init__(self, *, api_key=None, base_url=None, session=None):
        if api_key:
            self.api_key, self.source, self.configuration = api_key, "TRANSIENT", None
        else:
            self.api_key, self.source, self.configuration = effective_api_key()
        self.base_url = (base_url or settings.FINNHUB_BASE_URL).rstrip("/")
        self.session = session or requests.Session()

    def _record_state(self, response=None, error="", tested=False):
        config, _ = MarketDataProviderConfiguration.objects.get_or_create(provider="FINNHUB")
        fields = ["last_error", "rate_limit_state", "updated_at"]
        config.last_error = str(error)[:2000]
        if tested:
            config.last_tested_at = timezone.now()
            fields.append("last_tested_at")
        if response is not None:
            config.rate_limit_state = {
                "limit": response.headers.get("X-Ratelimit-Limit", ""),
                "remaining": response.headers.get("X-Ratelimit-Remaining", ""),
                "reset": response.headers.get("X-Ratelimit-Reset", ""),
            }
            if response.ok:
                config.last_success_at = timezone.now()
                fields.append("last_success_at")
        config.save(update_fields=list(dict.fromkeys(fields)))

    def get(self, path, params=None, *, tested=False):
        last_error = None
        for attempt in range(settings.FINNHUB_MAX_RETRIES + 1):
            try:
                response = self.session.get(
                    f"{self.base_url}/{path.lstrip('/')}",
                    params=params or {},
                    headers={"X-Finnhub-Token": self.api_key, "Accept": "application/json"},
                    timeout=settings.FINNHUB_REQUEST_TIMEOUT_SECONDS,
                )
                if response.status_code == 429:
                    last_error = FinnhubError("Finnhub rate limit exceeded", code="FINNHUB_RATE_LIMITED", status_code=429, retryable=True)
                elif response.status_code >= 500:
                    last_error = FinnhubError("Finnhub is temporarily unavailable", code="FINNHUB_UPSTREAM_ERROR", retryable=True)
                elif not response.ok:
                    last_error = FinnhubError(f"Finnhub rejected the request ({response.status_code})", code="FINNHUB_REQUEST_REJECTED", status_code=400)
                else:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise FinnhubError("Finnhub returned invalid JSON", code="FINNHUB_INVALID_RESPONSE") from exc
                    if isinstance(payload, dict) and payload.get("error"):
                        raise FinnhubError(str(payload["error"]), code="FINNHUB_REQUEST_REJECTED", status_code=400)
                    self._record_state(response, tested=tested)
                    return payload
                self._record_state(response, last_error, tested=tested)
                if not last_error.retryable or attempt >= settings.FINNHUB_MAX_RETRIES:
                    raise last_error
            except requests.RequestException as exc:
                last_error = FinnhubError("Unable to reach Finnhub", code="FINNHUB_UNAVAILABLE", retryable=True)
                self._record_state(error=last_error, tested=tested)
                if attempt >= settings.FINNHUB_MAX_RETRIES:
                    raise last_error from exc
            time.sleep(min(0.2 * (2 ** attempt), 1.0))
        raise last_error

    def test_connection(self, symbol="AAPL"):
        payload = self.get("quote", {"symbol": symbol}, tested=True)
        if not isinstance(payload, dict) or not payload.get("c"):
            raise FinnhubError("Finnhub quote test returned no current price", code="FINNHUB_TEST_FAILED", status_code=400)
        return {"connected": True, "symbol": symbol, "source": self.source}

    def daily_candles(self, symbol, start_date, end_date):
        start = int(datetime.combine(start_date, day_time.min, tzinfo=dt_timezone.utc).timestamp())
        end = int(datetime.combine(end_date, day_time.max, tzinfo=dt_timezone.utc).timestamp())
        payload = self.get("stock/candle", {"symbol": symbol, "resolution": "D", "from": start, "to": end})
        if payload.get("s") == "no_data":
            return []
        if payload.get("s") != "ok":
            raise FinnhubError("Finnhub candle response was not usable", code="FINNHUB_INVALID_RESPONSE")
        keys = ["t", "o", "h", "l", "c", "v"]
        lengths = {len(payload.get(key, [])) for key in keys}
        if len(lengths) != 1:
            raise FinnhubError("Finnhub candle arrays have inconsistent lengths", code="FINNHUB_INVALID_RESPONSE")
        return [
            {
                "trading_date": datetime.fromtimestamp(payload["t"][index], tz=dt_timezone.utc).date(),
                "open": Decimal(str(payload["o"][index])),
                "high": Decimal(str(payload["h"][index])),
                "low": Decimal(str(payload["l"][index])),
                "close": Decimal(str(payload["c"][index])),
                "adjusted_close": Decimal(str(payload["c"][index])),
                "volume": Decimal(str(payload["v"][index])),
            }
            for index in range(next(iter(lengths), 0))
        ]


@transaction.atomic
def fetch_daily_history(instrument, start_date, end_date, *, purpose="HISTORY", client=None):
    run = MarketDataFetchRun.objects.create(
        instrument=instrument, purpose=purpose, requested_start=start_date, requested_end=end_date
    )
    try:
        rows = (client or FinnhubClient()).daily_candles(instrument.symbol, start_date, end_date)
        written = 0
        now = timezone.now()
        for row in rows:
            _, created = InstrumentPriceHistory.objects.update_or_create(
                instrument=instrument,
                trading_date=row["trading_date"],
                provider="FINNHUB",
                defaults={**row, "quality_status": "COMPLETE", "fetched_at": now},
            )
            written += int(created)
        run.status = "COMPLETED"
        run.records_received = len(rows)
        run.records_written = written
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "records_received", "records_written", "completed_at"])
        return run
    except Exception as exc:
        run.status = "FAILED"
        run.error = str(exc)[:2000]
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "error", "completed_at"])
        raise
