from celery import shared_task
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from apps.audit.models import OutboxEvent
from apps.strategies.models import StrategyInstance
from .models import MarketDataSubscription,MarketBar
from .subscriptions import restore_market_subscriptions


@shared_task
def restore_active_market_subscriptions():return restore_market_subscriptions()


@shared_task
def monitor_market_data_providers():
    from apps.market_data.fallback import monitor_subscriptions
    return monitor_subscriptions()


@shared_task
def check_warmup_timeouts():
    now=timezone.now();cutoff=now-timedelta(seconds=int(getattr(settings,"WARMUP_TIMEOUT_SECONDS",300)));blocked=0
    for instance in StrategyInstance.objects.filter(enabled=True,state="WARMING_UP").select_related("instrument"):
        last=instance.warmup_last_progress_at or instance.warmup_started_at or instance.effective_from or instance.updated_at
        if last and last>cutoff:continue
        subscription=MarketDataSubscription.objects.filter(instrument=instance.instrument,timeframe=instance.timeframe).first()
        if not subscription:reason="no broker market-data subscription was created"
        elif subscription.state=="ERROR":reason=subscription.last_error or "both market-data providers are unusable"
        else:
            failed=OutboxEvent.objects.filter(status="FAILED",topic__in=["strategy.inputs.v1","market.raw.v1"]).order_by("-created_at").first()
            if failed:reason=f"Kafka publication failed: {failed.last_error}"
            elif subscription.last_event_at is None:reason=f"no usable provider event received (subscription {subscription.state})"
            elif not MarketBar.objects.filter(instrument=instance.instrument,interval=instance.timeframe,is_final=True).exists():reason="no final bar received from Flink"
            else:reason="required indicators did not become ready"
        instance.state="BLOCKED";instance.block_reason=f"Warm-up timeout: {reason}"[:255];instance.save(update_fields=["state","block_reason","updated_at"]);blocked+=1
    return blocked
