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
    evaluate_ready_strategies(bar)
    return {"bar_id": bar.pk}


def persist_indicator(envelope):
    payload = envelope["payload"]
    item, _ = IndicatorValue.objects.update_or_create(source_key=payload["source_key"],
        parameter_version=payload.get("parameter_version", 1), defaults={
            "instrument_id": payload["instrument_id"], "indicator": payload["indicator"],
            "value": Decimal(payload["value"]) if payload.get("value") is not None else None,
            "previous_value": Decimal(payload["previous_value"]) if payload.get("previous_value") is not None else None,
            "parameters": payload.get("parameters", {}), "parameters_hash": payload.get("parameters_hash", ""),
            "timeframe": payload.get("timeframe", ""), "source_bar_id": payload.get("source_bar_id", ""),
            "source_bar_version": payload.get("source_bar_version", 1), "is_final": payload.get("is_final", True),
            "event_time": _dt(payload["event_time"])})
    bar=MarketBar.objects.filter(bar_id=item.source_bar_id,version=item.source_bar_version,is_final=True).first()
    if bar:evaluate_ready_strategies(bar)
    return {"indicator_id": item.pk}


def _indicator_output_name(requirement):
    role=requirement.parameters.get("role")
    if requirement.name=="donchian":return "donchian_upper" if role=="entry" else "donchian_lower"
    return f"{requirement.name}_{role}" if role else requirement.name


def evaluate_ready_strategies(bar):
    """Evaluate active versions only after their exact final-bar inputs are persisted."""
    if not bar.is_final:return 0
    from apps.strategies.framework import evaluate_instance
    from apps.strategies.models import StrategyInstance
    instances=StrategyInstance.objects.filter(enabled=True,instrument=bar.instrument,timeframe=bar.interval,
        state__in=["WARMING_UP","FLAT","ENTRY_PENDING","PARTIALLY_LONG","LONG","EXIT_PENDING",
                   "PARTIALLY_SHORT","SHORT"]).select_related("definition","instrument","portfolio","legacy_strategy")
    evaluated=0
    for instance in instances:
        bindings=instance.input_bindings.filter(active=True,strategy_version__version=instance.version).select_related("requirement")
        indicator_requirements=[x.requirement for x in bindings if x.requirement.input_type=="INDICATOR"]
        values={};previous={};ready=True
        for requirement in indicator_requirements:
            value=IndicatorValue.objects.filter(instrument=instance.instrument,timeframe=instance.timeframe,
                source_bar_id=bar.bar_id,source_bar_version=bar.version,parameters_hash=requirement.parameters_hash,
                is_final=True).order_by("-created_at").first()
            if value is None:ready=False;break
            name=_indicator_output_name(requirement);values[name]=value.value;previous[name]=value.previous_value
        if not ready:continue
        payload={"bar_id":bar.bar_id,"event_id":f"{bar.bar_id}:{bar.version}","instrument_id":bar.instrument_id,
            "interval":bar.interval,"window_start":bar.window_start.isoformat(),"window_end":bar.window_end.isoformat(),
            "open":str(bar.open),"high":str(bar.high),"low":str(bar.low),"close":str(bar.close),"volume":str(bar.volume),
            "version":bar.version,"is_final":True}
        evaluate_instance(instance,bar=payload,indicators=values,previous_indicators=previous,
            event_id=payload["event_id"],source_data_version=bar.version,event_time=bar.window_end)
        evaluated+=1
    return evaluated


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
