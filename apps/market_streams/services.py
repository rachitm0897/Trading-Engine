from decimal import Decimal
from django.db import transaction
from django.utils.dateparse import parse_datetime
from apps.event_bus.services import consume_once
from .models import IndicatorValue, InstrumentMarketState, MarketBar


def _dt(value):
    return parse_datetime(value) if isinstance(value, str) else value


def persist_bar(envelope):
    payload = envelope["payload"]
    bar, _ = MarketBar.objects.update_or_create(bar_id=payload["bar_id"], version=payload.get("version", 1), defaults={
        "instrument_id": payload["instrument_id"], "interval": payload["interval"],
        "window_start": _dt(payload["window_start"]), "window_end": _dt(payload["window_end"]),
        "open": Decimal(payload["open"]), "high": Decimal(payload["high"]), "low": Decimal(payload["low"]),
        "close": Decimal(payload["close"]), "volume": Decimal(payload.get("volume", "0")),
        "is_final": payload.get("is_final", False), "source_event_count": payload.get("source_event_count", 0),
        "produced_at": _dt(envelope["produced_at"]),})
    return {"bar_id": bar.pk}


def persist_indicator(envelope):
    payload = envelope["payload"]
    item, _ = IndicatorValue.objects.update_or_create(source_key=payload["source_key"],
        parameter_version=payload.get("parameter_version", 1), defaults={
            "instrument_id": payload["instrument_id"], "indicator": payload["indicator"],
            "value": Decimal(payload["value"]) if payload.get("value") is not None else None,
            "parameters": payload.get("parameters", {}), "event_time": _dt(payload["event_time"])})
    return {"indicator_id": item.pk}


def persist_quality(envelope):
    payload = envelope["payload"]
    state, _ = InstrumentMarketState.objects.update_or_create(instrument_id=payload["instrument_id"], defaults={
        "status": payload["status"], "reference_price": payload.get("reference_price"),
        "latest_event_at": _dt(payload.get("latest_event_at")), "watermark_at": _dt(payload.get("watermark_at")),
        "stale_after_seconds": payload.get("stale_after_seconds", 300), "source_event_id": payload.get("source_event_id")})
    return {"market_state_id": state.pk}


def consume_market_event(consumer_name, envelope):
    handlers = {"market.bar": persist_bar, "market.indicator": persist_indicator, "market.quality": persist_quality}
    handler = handlers.get(envelope["event_type"])
    if not handler:
        raise ValueError(f"Unsupported market event type {envelope['event_type']}")
    return consume_once(consumer_name, envelope, handler)
