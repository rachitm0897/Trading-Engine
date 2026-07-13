from django.conf import settings
from django.utils import timezone
from .models import IndicatorValue, MarketBar, MarketDataSubscription


def strategy_stream_status(instance):
    from apps.strategies.plugins import get_plugin
    subscription=MarketDataSubscription.objects.filter(instrument=instance.instrument,timeframe=instance.timeframe).first()
    canonical=MarketBar.objects.filter(instrument=instance.instrument,interval=instance.timeframe).order_by("-produced_at","-version").first()
    final_bar=MarketBar.objects.filter(instrument=instance.instrument,interval=instance.timeframe,is_final=True).order_by("-window_end","-version").first()
    indicator=IndicatorValue.objects.filter(instrument=instance.instrument,timeframe=instance.timeframe,is_final=True).order_by("-event_time","-id").first()
    run=instance.runs.order_by("-started_at","-id").first()
    requires_indicator=instance.input_bindings.filter(active=True,strategy_version__version=instance.version,
        requirement__input_type="INDICATOR").exists()
    last_error=(subscription.last_error if subscription else "") or instance.block_reason
    missing=[]
    interval_seconds={"5s":5,"1m":60,"5m":300,"15m":900,"1h":3600,"1d":86400}.get(instance.timeframe,60)
    stale_after=max(settings.MARKET_PRICE_STALE_SECONDS,interval_seconds*2+60)
    now=timezone.now();stale=False
    if not subscription:missing.append("subscription")
    elif subscription.state!="ACTIVE":missing.append(f"subscription {subscription.state.lower()}")
    if not subscription or not subscription.last_event_at:missing.append("raw event")
    elif (now-subscription.last_event_at).total_seconds()>stale_after:missing.append("fresh raw event");stale=True
    if not canonical:missing.append("canonical event")
    elif (now-canonical.produced_at).total_seconds()>stale_after:missing.append("fresh canonical event");stale=True
    if not final_bar:missing.append("final bar")
    if requires_indicator and not indicator:missing.append("indicator")
    if final_bar and not run:missing.append("strategy run")
    status="DEGRADED" if stale or last_error or (subscription and subscription.state in {"ERROR","DEGRADED"}) else ("WARMING_UP" if missing else "HEALTHY")
    return {"strategy_id":instance.pk,"strategy":instance.name,"symbol":instance.instrument.symbol,
        "timeframe":instance.timeframe,"status":status,"subscription_state":subscription.state if subscription else "MISSING",
        "conid":subscription.conid if subscription else getattr(getattr(instance.instrument,"broker_contract",None),"conid",None),
        "last_raw_event":subscription.last_event_at if subscription else None,
        "last_canonical_event":canonical.produced_at if canonical else None,
        "last_final_bar":final_bar.window_end if final_bar else None,
        "warmup_progress":instance.warmup_progress,"warmup_required":get_plugin(instance.definition).warmup_bars(instance.parameters),
        "last_indicator":indicator.event_time if indicator else None,"last_strategy_run":run.started_at if run else None,
        "last_error":last_error,"missing":missing,"stale_after_seconds":stale_after}
