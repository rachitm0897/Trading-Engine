from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.db.models import F, Prefetch
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.event_bus.services import consume_once
from .models import IndicatorValue, InstrumentMarketState, MarketBar, StrategyEvaluationReadiness


def _dt(value):
    return parse_datetime(value) if isinstance(value, str) else value


def persist_bar(envelope):
    payload = envelope["payload"]
    was_final=MarketBar.objects.filter(bar_id=payload["bar_id"],is_final=True).exists()
    bar, _ = MarketBar.objects.update_or_create(bar_id=payload["bar_id"], version=payload.get("version", 1), defaults={
        "instrument_id": payload["instrument_id"], "interval": payload["interval"],
        "window_start": _dt(payload["window_start"]), "window_end": _dt(payload["window_end"]),
        "open": Decimal(payload["open"]), "high": Decimal(payload["high"]), "low": Decimal(payload["low"]),
        "close": Decimal(payload["close"]), "volume": Decimal(payload.get("volume", "0")),
        "is_final": payload.get("is_final", False), "source_event_count": payload.get("source_event_count", 0),
        "produced_at": _dt(envelope["produced_at"]),})
    update_warmup_progress(bar,new_final_bar=bar.is_final and not was_final)
    coordinate_bar_readiness(bar)
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
    if bar:
        if item.bar_id!=bar.pk:
            item.bar=bar;item.save(update_fields=["bar"])
        record_indicator_readiness(item,bar)
    return {"indicator_id": item.pk}


def _indicator_output_name(requirement):
    role=requirement.parameters.get("role")
    if requirement.name=="donchian":return "donchian_upper" if role=="entry" else "donchian_lower"
    return f"{requirement.name}_{role}" if role else requirement.name


def update_warmup_progress(bar,new_final_bar=False):
    if not bar.is_final:return 0
    from apps.strategies.models import StrategyInstance
    from apps.strategies.plugins import get_plugin
    instances=list(StrategyInstance.objects.filter(enabled=True,instrument=bar.instrument,timeframe=bar.interval).select_related("definition"))
    requirements={instance.pk:get_plugin(instance.definition).warmup_bars(instance.parameters) for instance in instances}
    maximum=max(requirements.values(),default=0)
    history_count=0
    if new_final_bar and any(instance.warmup_progress==0 for instance in instances):
        history_count=len(list(MarketBar.objects.filter(instrument=bar.instrument,interval=bar.interval,is_final=True)
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


def _evaluate_readiness(readiness_ids):
    from apps.strategies.framework import evaluate_instance
    evaluated=0
    for readiness_id in readiness_ids:
        with transaction.atomic():
            readiness=StrategyEvaluationReadiness.objects.select_for_update().select_related(
                "strategy_instance__definition","strategy_instance__instrument","strategy_instance__portfolio",
                "strategy_version","bar").get(pk=readiness_id)
            if readiness.status in {"COMPLETED","ERROR"}:
                continue
            if readiness.status=="EVALUATING" and readiness.claimed_at and readiness.claimed_at>timezone.now()-timedelta(minutes=5):
                continue
            if len(set(readiness.received_input_hashes))<readiness.expected_input_count:
                continue
            readiness.status="EVALUATING";readiness.claimed_at=timezone.now();readiness.last_error=""
            readiness.save(update_fields=["status","claimed_at","last_error","updated_at"])
        instance=readiness.strategy_instance;bar=readiness.bar
        bindings=list(instance.input_bindings.filter(active=True,strategy_version=readiness.strategy_version,
            requirement__input_type="INDICATOR").select_related("requirement"))
        values_by_hash={}
        for value in IndicatorValue.objects.filter(instrument=instance.instrument,timeframe=instance.timeframe,
                source_bar_id=bar.bar_id,source_bar_version=bar.version,is_final=True,
                parameters_hash__in=[binding.requirement.parameters_hash for binding in bindings]
                ).order_by("parameters_hash","-created_at"):
            values_by_hash.setdefault(value.parameters_hash,value)
        if len(values_by_hash)<len({binding.requirement.parameters_hash for binding in bindings}):
            StrategyEvaluationReadiness.objects.filter(pk=readiness.pk).update(status="PENDING",claimed_at=None)
            continue
        values={};previous={}
        for binding in bindings:
            value=values_by_hash[binding.requirement.parameters_hash]
            name=_indicator_output_name(binding.requirement);values[name]=value.value;previous[name]=value.previous_value
        payload={"bar_id":bar.bar_id,"event_id":f"{bar.bar_id}:{bar.version}","instrument_id":bar.instrument_id,
            "interval":bar.interval,"window_start":bar.window_start.isoformat(),"window_end":bar.window_end.isoformat(),
            "open":str(bar.open),"high":str(bar.high),"low":str(bar.low),"close":str(bar.close),"volume":str(bar.volume),
            "version":bar.version,"is_final":True}
        try:
            run=evaluate_instance(instance,bar=payload,indicators=values,previous_indicators=previous,
                event_id=payload["event_id"],source_data_version=bar.version,event_time=bar.window_end)
            status="ERROR" if run.status=="ERROR" else "COMPLETED"
            StrategyEvaluationReadiness.objects.filter(pk=readiness.pk).update(status=status,strategy_run=run,
                completed_at=timezone.now(),last_error=run.error[:1000])
            if run.status=="ERROR":raise RuntimeError(run.error or "Strategy evaluation failed")
            evaluated+=1
        except Exception as exc:
            StrategyEvaluationReadiness.objects.filter(pk=readiness.pk).update(status="ERROR",completed_at=timezone.now(),
                last_error=str(exc)[:1000])
            raise
    return evaluated


def coordinate_bar_readiness(bar):
    """Persist exact input readiness and evaluate each strategy/bar/version at most once."""
    if not bar.is_final:return 0
    instances=_active_instances_for_bar(bar)
    available=set(IndicatorValue.objects.filter(instrument=bar.instrument,timeframe=bar.interval,
        source_bar_id=bar.bar_id,source_bar_version=bar.version,is_final=True).values_list("parameters_hash",flat=True))
    existing={(row.strategy_instance_id,row.strategy_version_id):row for row in
        StrategyEvaluationReadiness.objects.filter(bar=bar,strategy_instance_id__in=[item.pk for item in instances])}
    creates=[];updates=[]
    for instance in instances:
        version=next((binding.strategy_version for binding in instance.ready_bindings
            if binding.strategy_version.version==instance.version),None)
        if version is None:
            version=instance.versions.filter(version=instance.version).first()
        if version is None:continue
        expected={binding.requirement.parameters_hash for binding in instance.ready_bindings
            if binding.strategy_version_id==version.pk and binding.requirement.input_type=="INDICATOR"}
        received=sorted(expected & available)
        readiness=existing.get((instance.pk,version.pk))
        if readiness is None:
            creates.append(StrategyEvaluationReadiness(strategy_instance=instance,strategy_version=version,bar=bar,
                expected_input_count=len(expected),received_input_hashes=received))
        elif readiness.status not in {"COMPLETED","ERROR","EVALUATING"} and (
                readiness.expected_input_count!=len(expected) or readiness.received_input_hashes!=received):
            readiness.expected_input_count=len(expected);readiness.received_input_hashes=received;updates.append(readiness)
    if creates:StrategyEvaluationReadiness.objects.bulk_create(creates,ignore_conflicts=True)
    if updates:StrategyEvaluationReadiness.objects.bulk_update(updates,["expected_input_count","received_input_hashes","updated_at"])
    ready_ids=list(StrategyEvaluationReadiness.objects.filter(bar=bar,status="PENDING").values_list("pk",flat=True))
    return _evaluate_readiness(ready_ids)


def record_indicator_readiness(indicator,bar):
    from apps.strategies.models import StrategyInputBinding
    pairs=list(StrategyInputBinding.objects.filter(active=True,requirement__parameters_hash=indicator.parameters_hash,
        strategy_instance__enabled=True,strategy_instance__instrument_id=indicator.instrument_id,
        strategy_instance__timeframe=indicator.timeframe,strategy_instance__state__in=ACTIVE_STRATEGY_STATES,
        strategy_version__version=F("strategy_instance__version")).values_list("strategy_instance_id","strategy_version_id"))
    if not pairs:return 0
    rows={(row.strategy_instance_id,row.strategy_version_id):row for row in StrategyEvaluationReadiness.objects.filter(
        bar=bar,strategy_instance_id__in=[pair[0] for pair in pairs],strategy_version_id__in=[pair[1] for pair in pairs])}
    if not rows:
        return coordinate_bar_readiness(bar)
    ready=[]
    with transaction.atomic():
        for pair in pairs:
            row=StrategyEvaluationReadiness.objects.select_for_update().get(pk=rows[pair].pk)
            if row.status!="PENDING":continue
            received=set(row.received_input_hashes);received.add(indicator.parameters_hash)
            row.received_input_hashes=sorted(received);row.save(update_fields=["received_input_hashes","updated_at"])
            if len(received)>=row.expected_input_count:ready.append(row.pk)
    return _evaluate_readiness(ready)


def evaluate_ready_strategies(bar):
    return coordinate_bar_readiness(bar)


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
