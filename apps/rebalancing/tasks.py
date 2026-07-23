from celery import shared_task
from django.utils import timezone
from apps.portfolios.models import TradingPortfolio
from .coordinator import process_target_coordination
from .services import plan_rebalance, recover_incomplete


@shared_task
def recover_incomplete_rebalances():
    return recover_incomplete()


@shared_task
def coordinate_portfolio_targets():
    return process_target_coordination()


@shared_task
def execute_rebalance_run(portfolio_id,trigger,idempotency_key,prices=None,nav=None,mode="SHADOW",
                          strict_market_state=True,available_cash=None):
    portfolio=TradingPortfolio.objects.select_related("account").get(pk=portfolio_id)
    try:
        from apps.allocation.models import RebalanceRun
        queued = RebalanceRun.objects.filter(idempotency_key=idempotency_key).select_related(
            "target_snapshot"
        ).first()
        run=plan_rebalance(portfolio,trigger,idempotency_key,prices=prices,nav=nav,mode=mode,
            strict_market_state=strict_market_state,available_cash=available_cash,
            target_snapshot=queued.target_snapshot if queued else None)
        return {"rebalance_run_id":run.pk,"status":run.status,"phase":run.phase}
    except Exception as exc:
        from apps.allocation.models import RebalanceRun
        RebalanceRun.objects.filter(idempotency_key=idempotency_key).update(status="FAILED",
            retryable=not isinstance(exc,ValueError),last_error=str(exc)[:1000],completed_at=timezone.now())
        raise
