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
        Q(enabled=True,state__in=["SUBSCRIBING","WARMING_UP"])
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
                else:reason="warm-up progress did not reach the current strategy requirements"
        instance.state="BLOCKED";instance.block_reason=f"Warm-up timeout: {reason}"[:255];instance.save(update_fields=["state","block_reason","updated_at"]);blocked+=1
        construction_run_id=instance.target_configuration.get("construction_run_id")
        if construction_run_id:
            from apps.portfolio_construction.services import record_strategy_activation_result
            record_strategy_activation_result(construction_run_id,instance.pk)
    for instance in StrategyInstance.objects.filter(
        enabled=True,state="READY_WAITING_FOR_LIVE_BAR"
    ).select_related("instrument","portfolio__gateway_session"):
        raw=str(instance.timeframe or "").strip().lower()
        units={"s":1,"m":60,"h":3600,"d":86400}
        interval_seconds=(
            int(raw[:-1])*units[raw[-1]]
            if len(raw)>1 and raw[:-1].isdigit() and raw[-1] in units
            else 60
        )
        timeout=max(
            int(getattr(settings,"LIVE_BAR_TIMEOUT_MIN_SECONDS",120)),
            interval_seconds*int(getattr(settings,"LIVE_BAR_TIMEOUT_MULTIPLIER",3))
            + int(getattr(settings,"LIVE_BAR_TIMEOUT_GRACE_SECONDS",60)),
        )
        waiting_since=(
            instance.ready_waiting_since or instance.warmup_completed_at
            or instance.warmup_last_progress_at or instance.updated_at
        )
        if waiting_since and waiting_since>now-timedelta(seconds=timeout):
            continue
        subscription=MarketDataSubscription.objects.filter(
            gateway_session=instance.portfolio.gateway_session,
            instrument=instance.instrument,timeframe=instance.timeframe,
        ).first()
        if subscription and subscription.state=="ERROR":
            reason=f"provider subscription failed: {subscription.last_error or 'unknown provider error'}"
        elif not subscription or subscription.state not in {"ACTIVE","DEGRADED"}:
            reason="provider subscription is not active"
        else:
            jobs=StrategyEvaluationJob.objects.filter(
                strategy_instance=instance,processing_mode="LIVE"
            ).order_by("-created_at")
            reason=(
                f"strategy evaluation job is {jobs.first().status.lower()}"
                if jobs.exists()
                else f"no final live {instance.timeframe} bar arrived"
            )
        instance.state="BLOCKED"
        instance.block_reason=f"Live-bar timeout ({timeout}s): {reason}"[:255]
        instance.save(update_fields=["state","block_reason","updated_at"])
        blocked+=1
        construction_run_id=instance.target_configuration.get("construction_run_id")
        if construction_run_id:
            from apps.portfolio_construction.services import record_strategy_activation_result
            record_strategy_activation_result(construction_run_id,instance.pk)
    return blocked
