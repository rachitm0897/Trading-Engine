from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from apps.audit.models import OutboxEvent
from apps.allocation.models import OrderIntentAttribution, RebalancePolicy, RebalanceRun, TargetPortfolioPosition
from apps.oms.models import OrderIntent
from apps.portfolios.models import PortfolioPosition
from apps.strategies.models import StrategyAllocation

D = Decimal


def aggregate_targets(portfolio):
    totals, attribution = {}, {}
    allocations = StrategyAllocation.objects.filter(portfolio=portfolio, strategy__enabled=True,
        strategy__kill_switch=False).select_related("strategy")
    for allocation in allocations:
        nav=D(portfolio.account.net_liquidation)
        capital_share = D(allocation.strategy.allocated_capital)/nav if nav>0 and allocation.strategy.allocated_capital>0 else D(allocation.weight)
        instance=getattr(allocation.strategy,"strategy_instance",None)
        if instance:
            latest_target=instance.targets.filter(run__status="COMPLETED",status="ACTIVE").order_by("-created_at").first()
            targets=[latest_target] if latest_target else []
        else:
            latest=allocation.strategy.runs.filter(status="COMPLETED").order_by("-completed_at").first()
            targets=list(latest.targets.all()) if latest else []
        for target in targets:
            contribution = D(target.target_weight) * capital_share
            totals[target.instrument_id] = totals.get(target.instrument_id, D(0)) + contribution
            attribution.setdefault(target.instrument_id, {})[allocation.strategy_id] = contribution
    return totals, attribution


def _round_lot(quantity, lot):
    return (quantity/lot).to_integral_value(rounding=ROUND_HALF_UP)*lot


def _floor_lot(quantity, lot):
    from decimal import ROUND_DOWN
    return max(D(0), (quantity/lot).to_integral_value(rounding=ROUND_DOWN)*lot)


def _reference_prices(portfolio, prices, strict):
    from apps.market_streams.models import InstrumentMarketState
    result, unusable = {}, set()
    if prices:
        result.update({key:D(str(value)) for key,value in prices.items() if not str(key).startswith("lot:")})
    for state in InstrumentMarketState.objects.filter(instrument_id__in=set(result) | set(
            PortfolioPosition.objects.filter(portfolio=portfolio).values_list("instrument_id", flat=True))):
        if state.is_usable() and state.reference_price:
            result[state.instrument_id] = D(state.reference_price)
        elif strict:
            unusable.add(state.instrument_id)
    return result, unusable


def _net_order_policy(portfolio, contributions, reference_price, side):
    """Select the highest-priority contributing policy for one net broker order."""
    allocations=StrategyAllocation.objects.filter(portfolio=portfolio,strategy_id__in=contributions).select_related(
        "strategy__strategy_instance__order_policy").order_by("priority","strategy_id")
    for allocation in allocations:
        instance=getattr(allocation.strategy,"strategy_instance",None)
        policy=instance.order_policy if instance else None
        if not policy:continue
        limit=None
        if policy.order_type=="LMT":
            offset=D(policy.limit_offset_bps)/D(10000)
            limit=reference_price*(D(1)+offset if side=="BUY" else D(1)-offset)
        return policy.order_type,policy.time_in_force,limit
    return "MKT","DAY",None


def _net_strategy_risk_limits(portfolio, contributions, reference_price, target_weight):
    policies=[]
    for allocation in StrategyAllocation.objects.filter(portfolio=portfolio,strategy_id__in=contributions).select_related(
            "strategy__strategy_instance__risk_policy"):
        instance=getattr(allocation.strategy,"strategy_instance",None)
        if instance and instance.risk_policy:policies.append(instance.risk_policy)
    if not policies:return {},{}
    maximum_quantity=min(min(D(x.maximum_quantity),D(x.maximum_notional)/reference_price) for x in policies)
    broker={"broker_max_quantity":maximum_quantity,"short_available":target_weight>=0 or all(x.allow_short for x in policies)}
    strategy={"max_weight":min(D(x.maximum_weight) for x in policies)}
    return broker,strategy


@transaction.atomic
def plan_rebalance(portfolio, trigger, idempotency_key, *, prices=None, nav=None, mode=None,
                   policy=None, strict_market_state=True):
    policy = policy or RebalancePolicy.objects.filter(portfolio=portfolio).first() or RebalancePolicy.objects.create(portfolio=portfolio)
    mode = (mode or policy.mode).upper()
    if mode not in {"SHADOW", "PAPER"}:
        raise ValueError("Rebalancing supports SHADOW or PAPER mode only")
    run, created = RebalanceRun.objects.get_or_create(idempotency_key=idempotency_key, defaults={
        "portfolio": portfolio, "policy": policy, "trigger": trigger, "mode": mode})
    if not created:
        return run
    nav = D(str(nav if nav is not None else portfolio.account.net_liquidation))
    if nav <= 0:
        raise ValueError("Portfolio NAV must be positive")
    current_rows = {x.instrument_id:x for x in PortfolioPosition.objects.filter(portfolio=portfolio).select_related("instrument")}
    target_weights, attribution = aggregate_targets(portfolio)
    instrument_ids = set(target_weights) | set(current_rows)
    reference, unusable = _reference_prices(portfolio, prices or {}, strict_market_state)
    missing = instrument_ids-set(reference)
    if missing:
        raise ValueError(f"No auditable reference price for instruments: {sorted(missing)}")
    run.nav = nav
    run.snapshot = {"nav":str(nav), "cash":str(portfolio.account.available_cash),
        "positions":{str(key):str(row.quantity) for key,row in current_rows.items()},
        "prices":{str(key):str(reference[key]) for key in instrument_ids}}
    candidates = []
    for instrument_id in instrument_ids:
        row = current_rows.get(instrument_id)
        instrument = row.instrument if row else __import__("apps.instruments.models", fromlist=["Instrument"]).Instrument.objects.get(pk=instrument_id)
        price, current = reference[instrument_id], D(row.quantity if row else 0)
        weight = D(target_weights.get(instrument_id, 0)); current_weight = current*price/nav
        drift = weight-current_weight
        lot = D(str((prices or {}).get(f"lot:{instrument_id}", instrument.lot_size)))
        target_qty = _round_lot(weight*nav/price, lot)
        delta = target_qty-current
        notional = abs(delta*price)
        reason = ""
        if instrument_id in unusable: reason = "STALE_OR_UNAVAILABLE_PRICE"
        elif abs(drift) < policy.instrument_drift_threshold and trigger not in {"MANUAL", "SCHEDULED", "DEPOSIT", "WITHDRAWAL"}: reason = "BELOW_DRIFT_THRESHOLD"
        elif abs(delta) < policy.minimum_trade_quantity: reason = "BELOW_MINIMUM_QUANTITY"
        elif notional < policy.minimum_trade_notional: reason = "BELOW_MINIMUM_NOTIONAL"
        elif strict_market_state and not hasattr(instrument, "broker_contract"): reason = "UNQUALIFIED_CONTRACT"
        estimated_cost = policy.fee_buffer + notional*D("0.0005")
        benefit = abs(drift)*nav
        if not reason and estimated_cost >= benefit: reason = "COST_EXCEEDS_BENEFIT"
        candidates.append({"instrument":instrument, "weight":weight, "current":current, "current_weight":current_weight,
            "drift":drift, "target":target_qty, "delta":delta, "price":price, "lot":lot,
            "estimated_cost":estimated_cost, "reason":reason})
    candidates.sort(key=lambda x: (0 if x["delta"]<0 else 1, -abs(x["drift"]), x["estimated_cost"], x["instrument"].pk))
    turnover_used = D(0)
    has_sells = any(x["delta"] < 0 and not x["reason"] for x in candidates)
    buy_cash = max(D(portfolio.account.available_cash)*(D(1)-D(policy.cash_buffer_percent)), D(0))
    for rank, item in enumerate(candidates):
        trade_turnover = abs(item["delta"]*item["price"])/nav
        if not item["reason"] and turnover_used+trade_turnover > policy.maximum_turnover:
            item["reason"] = "TURNOVER_LIMIT"
        if not item["reason"]:
            turnover_used += trade_turnover
        item["desired_delta"] = item["delta"]
        if not item["reason"] and item["delta"] > 0 and not (policy.sell_before_buy and has_sells):
            affordable = _floor_lot(max(buy_cash-D(policy.fee_buffer), D(0))/item["price"], item["lot"])
            if affordable < item["delta"]:
                item["delta"] = affordable
            if item["delta"] <= 0:
                item["reason"] = "CASH_OR_FEE_BUFFER"
            else:
                buy_cash -= item["delta"]*item["price"]+D(policy.fee_buffer)
        item["target_row"] = TargetPortfolioPosition.objects.create(rebalance=run, instrument=item["instrument"],
            target_weight=item["weight"], target_quantity=item["target"], trade_quantity=D(0) if item["reason"] else item["delta"],
            reference_price=item["price"], current_quantity=item["current"], current_weight=item["current_weight"],
            drift=item["drift"], lot_size=item["lot"], estimated_cost=item["estimated_cost"],
            suppressed=bool(item["reason"]), suppression_reason=item["reason"], rank=rank)
    run.total_drift = sum(abs(x["drift"]) for x in candidates)
    run.planned_turnover = turnover_used
    run.phase = "SHADOW_COMPLETE" if mode == "SHADOW" else ("SELLS" if policy.sell_before_buy and has_sells else "BUYS")
    run.status = "PLANNED" if mode == "SHADOW" else "INTENTS_CREATED"
    run.last_recalculated_at = timezone.now()
    run.save(update_fields=["nav","snapshot","total_drift","planned_turnover","phase","status","last_recalculated_at"])
    if mode == "PAPER":
        for item in candidates:
            if item["reason"] or not item["delta"]:
                continue
            is_buy = item["delta"] > 0
            eligible = not (policy.sell_before_buy and is_buy and run.phase == "SELLS")
            contributions = attribution.get(item["instrument"].pk, {})
            order_type,tif,limit_price=_net_order_policy(portfolio,contributions,item["price"],"BUY" if is_buy else "SELL")
            version_ids=[]
            for strategy_id in contributions:
                strategy=StrategyAllocation.objects.filter(portfolio=portfolio,strategy_id=strategy_id).select_related("strategy").first().strategy
                instance=getattr(strategy,"strategy_instance",None)
                if instance:
                    version=instance.versions.filter(version=instance.version).first()
                    if version:version_ids.append(version.pk)
            intent = OrderIntent.objects.create(rebalance=run, portfolio=portfolio, instrument=item["instrument"],
                side="BUY" if is_buy else "SELL", quantity=abs(item["delta"]), reference_price=item["price"],
                order_type=order_type,time_in_force=tif,limit_price=limit_price,strategy_version_snapshot=sorted(version_ids),
                idempotency_key=f"rebalance:{run.pk}:instrument:{item['instrument'].pk}:v1", source="REBALANCE",
                mode="PAPER", requires_fresh_price=True, execution_priority=item["target_row"].rank, eligible=eligible)
            if strict_market_state:
                from apps.position_sizing.models import PositionSizingPolicy
                from apps.position_sizing.services import size_and_record
                from apps.market_streams.models import IndicatorValue
                sizing_policy = PositionSizingPolicy.objects.filter(portfolio=portfolio, enabled=True).first() or PositionSizingPolicy.objects.create(portfolio=portfolio)
                adv_record = IndicatorValue.objects.filter(instrument=item["instrument"], indicator="average_volume").order_by("-event_time").first()
                broker_limits,strategy_limits=_net_strategy_risk_limits(portfolio,contributions,item["price"],item["weight"])
                size_and_record(sizing_policy, item["instrument"], intent.side, intent.quantity, item["price"], None, nav,
                    portfolio.account.available_cash, adv_record.value if adv_record and adv_record.value is not None else 0,
                    broker_limits=broker_limits,strategy_limits=strategy_limits,order_intent=intent,
                    idempotency_key=f"sizing:rebalance:{run.pk}:instrument:{item['instrument'].pk}:v1")
            net_contribution = sum(contributions.values()) or D(1)
            for strategy_id, contribution in contributions.items():
                strategy = StrategyAllocation.objects.select_related("strategy").filter(
                    portfolio=portfolio, strategy_id=strategy_id).first().strategy
                instance = getattr(strategy, "strategy_instance", None)
                OrderIntentAttribution.objects.create(order_intent=intent, strategy_id=strategy_id,
                    strategy_instance=instance,
                    strategy_version=instance.versions.filter(version=instance.version).first() if instance else None,
                    target_delta=contribution, allocated_quantity=item["delta"]*contribution/net_contribution)
    OutboxEvent.objects.create(topic="portfolio.rebalance.planned.v1", event_type="portfolio.rebalance.planned",
        aggregate_type="portfolio", aggregate_id=str(portfolio.pk), partition_key=str(portfolio.pk),
        payload={"rebalance_run_id":run.pk,"mode":mode,"phase":run.phase,"turnover":str(turnover_used)},
        idempotency_key=f"rebalance:{run.pk}:planned")
    return run


@transaction.atomic
def advance_rebalance(run):
    run = RebalanceRun.objects.select_for_update().get(pk=run.pk)
    if run.mode != "PAPER" or run.phase != "SELLS":
        return run
    sell_intents = OrderIntent.objects.filter(rebalance=run, side="SELL")
    requested = sum((D(x.quantity) for x in sell_intents), D(0))
    filled = sum((D(x.order.filled_quantity) for x in sell_intents if hasattr(x, "order")), D(0))
    threshold = D(run.policy.partial_fill_threshold if run.policy else "0.95")
    terminal = all(hasattr(x,"order") and x.order.status in {"FILLED","CANCELLED","REJECTED","EXPIRED"} for x in sell_intents)
    if requested == 0 or filled/requested >= threshold or terminal:
        portfolio = run.portfolio
        cash = max(D(portfolio.account.available_cash)*(D(1)-D(run.policy.cash_buffer_percent)), D(0))
        positions = {x.instrument_id:D(x.quantity) for x in PortfolioPosition.objects.filter(portfolio=portfolio)}
        for target in run.targets.filter(trade_quantity__gt=0).order_by("rank"):
            intent = OrderIntent.objects.filter(rebalance=run, instrument=target.instrument, side="BUY").first()
            if not intent or hasattr(intent, "order"):
                continue
            desired = max(D(target.target_quantity)-positions.get(target.instrument_id,D(0)),D(0))
            affordable = _floor_lot(max(cash-D(run.policy.fee_buffer),D(0))/D(target.reference_price),D(target.lot_size))
            quantity = min(desired, affordable)
            if quantity > 0:
                intent.quantity=quantity;intent.eligible=True;intent.save(update_fields=["quantity","eligible"])
                target.trade_quantity=quantity;target.save(update_fields=["trade_quantity"])
                cash -= quantity*D(target.reference_price)+D(run.policy.fee_buffer)
            else:
                target.trade_quantity=0;target.suppressed=True;target.suppression_reason="CASH_OR_FEE_BUFFER"
                target.save(update_fields=["trade_quantity","suppressed","suppression_reason"])
        run.phase = "BUYS"; run.last_recalculated_at = timezone.now(); run.save(update_fields=["phase","last_recalculated_at"])
    return run


def recover_incomplete():
    recovered = 0
    for run in RebalanceRun.objects.filter(status__in=["INTENTS_CREATED", "EXECUTING"], mode="PAPER"):
        if run.phase == "SELLS":
            advance_rebalance(run)
        else:
            positions = {x.instrument_id:D(x.quantity) for x in PortfolioPosition.objects.filter(portfolio=run.portfolio)}
            for target in run.targets.filter(suppressed=False):
                desired = D(target.target_quantity)-positions.get(target.instrument_id,D(0))
                side = "BUY" if desired > 0 else "SELL"
                remaining = abs(desired)
                if remaining < D(target.lot_size):
                    continue
                intents = OrderIntent.objects.filter(rebalance=run,instrument=target.instrument,side=side)
                if intents.filter(order__status__in=["CREATED","RISK_APPROVED","QUEUED","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED","CANCEL_PENDING","UNKNOWN"]).exists() or intents.filter(order__isnull=True).exists():
                    continue
                version = intents.count()+1
                OrderIntent.objects.get_or_create(idempotency_key=f"rebalance:{run.pk}:instrument:{target.instrument_id}:recovery:{version}",defaults={
                    "rebalance":run,"portfolio":run.portfolio,"instrument":target.instrument,"side":side,
                    "quantity":remaining,"reference_price":target.reference_price,"source":"REBALANCE","mode":"PAPER",
                    "requires_fresh_price":True,"execution_priority":target.rank,"eligible":True})
        recovered += 1
    return recovered
