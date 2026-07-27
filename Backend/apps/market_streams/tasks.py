from celery import shared_task
from datetime import timedelta
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from apps.audit.models import OutboxEvent
from apps.strategies.models import StrategyInstance
from .models import IndicatorValue,MarketDataSubscription,MarketBar,StrategyEvaluationJob
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
    query=StrategyInstance.objects.filter(
        Q(enabled=True,state__in=["SUBSCRIBING","WARMING_UP","READY_WAITING_FOR_LIVE_BAR"])
        | Q(state="ACTIVATING")
    ).select_related("instrument","portfolio__gateway_session")
    for instance in query:
        last=instance.warmup_last_progress_at or instance.warmup_started_at or instance.effective_from or instance.updated_at
        if last and last>cutoff:continue
        subscription=MarketDataSubscription.objects.filter(gateway_session=instance.portfolio.gateway_session,
            instrument=instance.instrument,timeframe=instance.timeframe).first()
        if not subscription:reason="no market-data subscription was created"
        elif subscription.state in {"PENDING","SUBSCRIBING"}:
            reason="subscription command is still pending"
            subscription.state="ERROR"
            subscription.last_error=reason
            subscription.save(update_fields=["state","last_error","updated_at"])
        elif subscription.state=="ERROR":
            reason=f"subscription failed: {subscription.last_error or 'market-data providers are unusable'}"
        else:
            failed=OutboxEvent.objects.filter(status="FAILED",topic__in=["strategy.inputs.v1","market.raw.v1"]).order_by("-created_at").first()
            if failed:reason=f"Kafka publication failed: {failed.last_error}"
            elif subscription.last_event_at is None:reason="no raw provider event received"
            elif not MarketBar.objects.filter(instrument=instance.instrument,interval=instance.timeframe).exists():
                reason="no canonical event produced"
            elif not MarketBar.objects.filter(instrument=instance.instrument,interval=instance.timeframe,is_final=True).exists():
                reason="no final bar produced"
            else:
                indicator_hashes=list(instance.input_bindings.filter(
                    active=True,strategy_version__version=instance.version,
                    requirement__input_type="INDICATOR",
                ).values_list("requirement__identity_hash",flat=True))
                available=set(IndicatorValue.objects.filter(
                    instrument=instance.instrument,timeframe=instance.timeframe,is_final=True,
                    requirement_identity_hash__in=indicator_hashes,
                ).values_list("requirement_identity_hash",flat=True))
                if not set(indicator_hashes).issubset(available):
                    reason="required indicators missing"
                elif instance.state=="READY_WAITING_FOR_LIVE_BAR":
                    jobs=StrategyEvaluationJob.objects.filter(
                        strategy_instance=instance,processing_mode="LIVE").order_by("-created_at")
                    if not jobs.exists():
                        reason="strategy evaluation job not scheduled"
                    else:
                        from apps.event_bus.models import StreamHealthMetric
                        heartbeat=StreamHealthMetric.objects.filter(
                            component="execution-worker",metric="strategy_evaluation").first()
                        stale_seconds=int(getattr(settings,"EXECUTION_WORKER_HEARTBEAT_STALE_SECONDS",120))
                        if (not heartbeat or (now-heartbeat.observed_at).total_seconds()>stale_seconds):
                            reason="strategy evaluation worker unavailable"
                        else:
                            latest=jobs.first()
                            reason=f"strategy evaluation job is {latest.status.lower()}"
                else:reason="warm-up progress did not reach the current strategy requirements"
        instance.state="BLOCKED";instance.block_reason=f"Warm-up timeout: {reason}"[:255];instance.save(update_fields=["state","block_reason","updated_at"]);blocked+=1
        construction_run_id=instance.target_configuration.get("construction_run_id")
        if construction_run_id:
            from apps.portfolio_construction.services import record_strategy_activation_result
            record_strategy_activation_result(construction_run_id,instance.pk)
    return blocked
