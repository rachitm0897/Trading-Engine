from decimal import Decimal
from django.db import transaction
from django.db.models import F, Max, Prefetch
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.event_bus.identity import processing_mode
from apps.event_bus.services import consume_once
from .models import IndicatorValue, InstrumentMarketState, MarketBar, StrategyEvaluationReadiness


def _dt(value):
    return parse_datetime(value) if isinstance(value, str) else value


def _assert_same_market_fact(kind, actual, expected):
    differences = [
        field
        for field, value in expected.items()
        if getattr(actual, field) != value
    ]
    if differences:
        raise ValueError(
            f"Conflicting {kind} payload for deterministic identity: "
            + ", ".join(sorted(differences))
        )


@transaction.atomic
def persist_bar(envelope):
    payload = envelope["payload"]
    mode=processing_mode(payload.get("processing_mode"))
    was_final=MarketBar.objects.filter(
        bar_id=payload["bar_id"],
        is_final=True,
        processing_mode__in=["LIVE","WARMUP"],
    ).exists()
    bar, created = MarketBar.objects.get_or_create(bar_id=payload["bar_id"], version=payload.get("version", 1), defaults={
        "instrument_id": payload["instrument_id"], "interval": payload["interval"],
        "window_start": _dt(payload["window_start"]), "window_end": _dt(payload["window_end"]),
        "open": Decimal(payload["open"]), "high": Decimal(payload["high"]), "low": Decimal(payload["low"]),
        "close": Decimal(payload["close"]), "volume": Decimal(payload.get("volume", "0")),
        "is_final": payload.get("is_final", False), "source_event_count": payload.get("source_event_count", 0),
        "processing_mode":mode,"produced_at": _dt(envelope["produced_at"]),})
    promoted_to_live=False
    if not created:
        bar=MarketBar.objects.select_for_update().get(pk=bar.pk)
        _assert_same_market_fact("bar",bar,{
            "instrument_id":int(payload["instrument_id"]),
            "interval":payload["interval"],
            "window_start":_dt(payload["window_start"]),
            "window_end":_dt(payload["window_end"]),
            "open":Decimal(payload["open"]),
            "high":Decimal(payload["high"]),
            "low":Decimal(payload["low"]),
            "close":Decimal(payload["close"]),
            "volume":Decimal(payload.get("volume","0")),
            "is_final":payload.get("is_final",False),
            "source_event_count":payload.get("source_event_count",0),
        })
        if mode=="LIVE" and bar.processing_mode!="LIVE":
            bar.processing_mode="LIVE";bar.save(update_fields=["processing_mode"])
            promoted_to_live=True
    if (created and mode in {"LIVE","WARMUP"}) or promoted_to_live:
        update_warmup_progress(bar,new_final_bar=bar.is_final and not was_final)
    if mode=="LIVE":
        coordinate_bar_readiness(bar, event_id=envelope.get("event_id"))
    return {"bar_id": bar.pk}


@transaction.atomic
def persist_indicator(envelope):
    payload = envelope["payload"]
    mode=processing_mode(payload.get("processing_mode"))
    identity_hash=str(payload.get("requirement_identity_hash") or "")
    if len(identity_hash)!=64:
        raise ValueError("Indicator event is missing a full requirement identity hash")
    item, created = IndicatorValue.objects.get_or_create(source_key=payload["source_key"],defaults={
            "instrument_id": payload["instrument_id"], "indicator": payload["indicator"],
            "indicator_name":payload["indicator_name"],"indicator_role":payload.get("indicator_role",""),
            "implementation_version":payload.get("implementation_version",1),
            "requirement_identity_hash":identity_hash,
            "value": Decimal(payload["value"]) if payload.get("value") is not None else None,
            "previous_value": Decimal(payload["previous_value"]) if payload.get("previous_value") is not None else None,
            "parameters": payload.get("parameters", {}),
            "timeframe": payload.get("timeframe", ""), "source_bar_id": payload.get("source_bar_id", ""),
            "source_bar_version": payload.get("source_bar_version", 1), "is_final": payload.get("is_final", True),
            "processing_mode":mode,"event_time": _dt(payload["event_time"])})
    if not created:
        item=IndicatorValue.objects.select_for_update().get(pk=item.pk)
        _assert_same_market_fact("indicator",item,{
            "instrument_id":int(payload["instrument_id"]),
            "indicator":payload["indicator"],
            "indicator_name":payload["indicator_name"],
            "indicator_role":payload.get("indicator_role",""),
            "implementation_version":payload.get("implementation_version",1),
            "requirement_identity_hash":identity_hash,
            "value":Decimal(payload["value"]) if payload.get("value") is not None else None,
            "previous_value":Decimal(payload["previous_value"]) if payload.get("previous_value") is not None else None,
            "parameters":payload.get("parameters",{}),
            "timeframe":payload.get("timeframe",""),
            "source_bar_id":payload.get("source_bar_id",""),
            "source_bar_version":payload.get("source_bar_version",1),
            "is_final":payload.get("is_final",True),
            "event_time":_dt(payload["event_time"]),
        })
        if mode=="LIVE" and item.processing_mode!="LIVE":
            item.processing_mode="LIVE";item.save(update_fields=["processing_mode"])
    bar=MarketBar.objects.filter(bar_id=item.source_bar_id,version=item.source_bar_version,is_final=True).first()
    if bar:
        if item.bar_id!=bar.pk:
            item.bar=bar;item.save(update_fields=["bar"])
        if mode=="LIVE" and bar.processing_mode=="LIVE":
            coordinate_bar_readiness(bar)
    return {"indicator_id": item.pk}


def update_warmup_progress(bar,new_final_bar=False):
    if not bar.is_final:return 0
    from apps.strategies.models import StrategyInputBinding, StrategyInstance
    instances=list(StrategyInstance.objects.filter(
        enabled=True,instrument=bar.instrument,timeframe=bar.interval))
    required_by_instance=dict(
        StrategyInputBinding.objects.filter(
            active=True,
            strategy_instance_id__in=[instance.pk for instance in instances],
            strategy_version__version=F("strategy_instance__version"),
        )
        .values("strategy_instance_id")
        .annotate(required=Max("requirement__warmup_bars"))
        .values_list("strategy_instance_id","required")
    )
    requirements={instance.pk:required_by_instance.get(instance.pk,0) or 0 for instance in instances}
    maximum=max(requirements.values(),default=0)
    history_count=0
    if new_final_bar and any(instance.warmup_progress==0 for instance in instances):
        history_count=len(list(MarketBar.objects.filter(instrument=bar.instrument,interval=bar.interval,is_final=True)
            .filter(processing_mode__in=["LIVE","WARMUP"])
            .values_list("bar_id",flat=True).distinct()[:maximum]))
    changed=[];now=timezone.now()
    for instance in instances:
        required=requirements[instance.pk]
        value=instance.warmup_progress
        if new_final_bar:
            value=min(history_count if instance.warmup_progress==0 else instance.warmup_progress+1,required)
        dirty=False
        if value!=instance.warmup_progress:
            instance.warmup_progress=value;instance.warmup_last_progress_at=now;dirty=True
        if instance.state=="BLOCKED" and instance.block_reason.startswith("Warm-up timeout:"):
            instance.state="WARMING_UP";instance.block_reason="";dirty=True
        if dirty:
            instance.updated_at=now;changed.append(instance)
    if changed:
        StrategyInstance.objects.bulk_update(changed,["warmup_progress","warmup_last_progress_at","state","block_reason","updated_at"])
    return len(changed)


ACTIVE_STRATEGY_STATES=["WARMING_UP","FLAT","ENTRY_PENDING","PARTIALLY_LONG","LONG","EXIT_PENDING",
    "PARTIALLY_SHORT","SHORT"]


def _active_instances_for_bar(bar):
    from apps.strategies.models import StrategyInputBinding, StrategyInstance
    bindings=StrategyInputBinding.objects.filter(active=True).select_related("requirement","strategy_version")
    return list(StrategyInstance.objects.filter(enabled=True,instrument=bar.instrument,timeframe=bar.interval,
        state__in=ACTIVE_STRATEGY_STATES).select_related("definition","instrument","portfolio").prefetch_related(
            Prefetch("input_bindings",queryset=bindings,to_attr="ready_bindings")))


def coordinate_bar_readiness(bar, event_id=None):
    """Persist exact input readiness and schedule each strategy/bar/version at most once."""
    if not bar.is_final or bar.processing_mode!="LIVE":return 0
    from apps.strategies.evaluation_jobs import ensure_strategy_evaluation_job
    instances=_active_instances_for_bar(bar)
    available=set(IndicatorValue.objects.filter(instrument=bar.instrument,timeframe=bar.interval,
        source_bar_id=bar.bar_id,source_bar_version=bar.version,is_final=True,processing_mode="LIVE"
        ).values_list("requirement_identity_hash",flat=True))
    existing={(row.strategy_instance_id,row.strategy_version_id):row for row in
        StrategyEvaluationReadiness.objects.filter(bar=bar,strategy_instance_id__in=[item.pk for item in instances])}
    creates=[];job_inputs={}
    for instance in instances:
        version=next((binding.strategy_version for binding in instance.ready_bindings
            if binding.strategy_version.version==instance.version),None)
        if version is None:
            version=instance.versions.filter(version=instance.version).first()
        if version is None:continue
        expected={binding.requirement.identity_hash for binding in instance.ready_bindings
            if binding.strategy_version_id==version.pk and binding.requirement.input_type=="INDICATOR"}
        identities={binding.requirement.identity_hash for binding in instance.ready_bindings
            if binding.strategy_version_id==version.pk}
        job_inputs[(instance.pk,version.pk)]=(sorted(identities),expected.issubset(available))
        readiness=existing.get((instance.pk,version.pk))
        if readiness is None:
            creates.append(StrategyEvaluationReadiness(strategy_instance=instance,strategy_version=version,bar=bar))
    if creates:StrategyEvaluationReadiness.objects.bulk_create(creates,ignore_conflicts=True)
    readiness_rows=StrategyEvaluationReadiness.objects.filter(
        bar=bar,
        strategy_instance_id__in=[item.pk for item in instances],
    )
    scheduled=0
    for readiness in readiness_rows:
        inputs=job_inputs.get((readiness.strategy_instance_id,readiness.strategy_version_id))
        if inputs is None:continue
        _,became_ready=ensure_strategy_evaluation_job(
            readiness,
            expected_input_identity_hashes=inputs[0],
            ready=inputs[1],
            event_id=event_id,
        )
        scheduled+=int(became_ready)
    return scheduled


def persist_quality(envelope):
    import uuid
    payload = envelope["payload"]
    mode=processing_mode(payload.get("processing_mode"))
    if mode!="LIVE":
        return {"ignored_processing_mode":mode}
    source_value=payload.get("source_event_id")
    try:source_uuid=uuid.UUID(str(source_value)) if source_value else None
    except (ValueError,TypeError,AttributeError):source_uuid=uuid.uuid5(uuid.NAMESPACE_URL,str(source_value))
    state, _ = InstrumentMarketState.objects.update_or_create(instrument_id=payload["instrument_id"], defaults={
        "status": payload["status"], "reference_price": payload.get("reference_price"),
        "latest_event_at": _dt(payload.get("latest_event_at")), "watermark_at": _dt(payload.get("watermark_at")),
        "stale_after_seconds": payload.get("stale_after_seconds", 300), "source_event_id":source_uuid,
        "reference_price_provider":payload.get("provider", ""),
        "reference_price_source":payload.get("source", ""),
        "provider_generation":payload.get("provider_generation") or None})
    return {"market_state_id": state.pk}


def consume_market_event(consumer_name, envelope):
    handlers = {"market.bar": persist_bar, "market.indicator": persist_indicator, "market.quality": persist_quality}
    handler = handlers.get(envelope["event_type"])
    if not handler:
        raise ValueError(f"Unsupported market event type {envelope['event_type']}")
    return consume_once(consumer_name, envelope, handler)
