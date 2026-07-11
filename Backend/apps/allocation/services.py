from decimal import Decimal, ROUND_DOWN
from django.db import transaction
from apps.oms.models import OrderIntent
from apps.portfolios.models import PortfolioPosition
from apps.strategies.models import StrategyAllocation, StrategyTarget
from .models import RebalanceRun, TargetPortfolioPosition

def aggregate_targets(portfolio):
    totals = {}
    allocations = StrategyAllocation.objects.filter(portfolio=portfolio, strategy__enabled=True, strategy__kill_switch=False).select_related("strategy")
    for allocation in allocations:
        latest = allocation.strategy.runs.filter(status="COMPLETED").order_by("-completed_at").first()
        if not latest: continue
        for target in latest.targets.all():
            totals[target.instrument_id] = totals.get(target.instrument_id, Decimal(0)) + target.target_weight * allocation.weight
    return totals

@transaction.atomic
def create_rebalance(portfolio, prices, nav, trigger, idempotency_key):
    rebalance, created = RebalanceRun.objects.get_or_create(idempotency_key=idempotency_key, defaults={"portfolio": portfolio, "trigger": trigger})
    if not created: return rebalance
    current = {p.instrument_id: p.quantity for p in PortfolioPosition.objects.filter(portfolio=portfolio)}
    for instrument_id, weight in aggregate_targets(portfolio).items():
        price = Decimal(str(prices[instrument_id])); lot = Decimal(str(prices.get(f"lot:{instrument_id}", 1)))
        raw_target = Decimal(nav) * weight / price
        target_qty = (raw_target / lot).to_integral_value(rounding=ROUND_DOWN) * lot
        delta = target_qty - current.get(instrument_id, Decimal(0))
        notional = abs(delta * price)
        if abs(delta) < portfolio.minimum_quantity or notional < portfolio.minimum_notional: delta = Decimal(0)
        target = TargetPortfolioPosition.objects.create(rebalance=rebalance, instrument_id=instrument_id, target_weight=weight, target_quantity=target_qty, trade_quantity=delta, reference_price=price)
        if delta:
            OrderIntent.objects.create(rebalance=rebalance, portfolio=portfolio, instrument_id=instrument_id, side="BUY" if delta > 0 else "SELL", quantity=abs(delta), reference_price=price, idempotency_key=f"rebalance:{rebalance.pk}:target:{target.pk}")
    rebalance.status = "INTENTS_CREATED"; rebalance.save(update_fields=["status"])
    return rebalance
