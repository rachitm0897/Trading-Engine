from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from apps.audit.models import OutboxEvent
from apps.core.idempotency import canonical_request_hash, require_matching_request
from apps.allocation.models import OrderIntentAttribution, RebalancePolicy, RebalanceRun, TargetPortfolioPosition
from apps.oms.models import OrderIntent
from apps.portfolios.models import PortfolioPosition
from apps.strategies.models import StrategyAllocation, StrategyTarget

D = Decimal
VARIABLE_FEE_RATE = D("0.0005")


def aggregate_targets(portfolio):
    totals, attribution = {}, {}
    allocations = list(StrategyAllocation.objects.filter(portfolio=portfolio, strategy_instance__enabled=True,
        strategy_instance__kill_switch=False).select_related("strategy_instance"))
    latest_targets = {}
    for target in StrategyTarget.objects.filter(
            strategy_instance_id__in=[item.strategy_instance_id for item in allocations],
            run__status="COMPLETED", status="ACTIVE").order_by("strategy_instance_id", "-created_at"):
        latest_targets.setdefault(target.strategy_instance_id, target)
    for allocation in allocations:
        nav=D(portfolio.account.net_liquidation)
        instance=allocation.strategy_instance
        capital_share = D(instance.allocated_capital)/nav if nav>0 and instance.allocated_capital>0 else D(allocation.weight)
        target = latest_targets.get(instance.pk)
        if target:
            contribution = D(target.target_weight) * capital_share
            totals[target.instrument_id] = totals.get(target.instrument_id, D(0)) + contribution
            attribution.setdefault(target.instrument_id, {})[instance.pk] = contribution
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
    allocations=StrategyAllocation.objects.filter(portfolio=portfolio,strategy_instance_id__in=contributions).select_related(
        "strategy_instance__order_policy").order_by("priority","strategy_instance_id")
    for allocation in allocations:
        policy=allocation.strategy_instance.order_policy
        if not policy:continue
        limit=None
        if policy.order_type=="LMT":
            offset=D(policy.limit_offset_bps)/D(10000)
            limit=reference_price*(D(1)+offset if side=="BUY" else D(1)-offset)
        return policy.order_type,policy.time_in_force,limit
    return "MKT","DAY",None


def _net_strategy_risk_limits(portfolio, contributions, reference_price, target_weight):
    policies=[]
    for allocation in StrategyAllocation.objects.filter(portfolio=portfolio,strategy_instance_id__in=contributions).select_related(
            "strategy_instance__risk_policy"):
        if allocation.strategy_instance.risk_policy:policies.append(allocation.strategy_instance.risk_policy)
    if not policies:return {},{}
    maximum_quantity=min(min(D(x.maximum_quantity),D(x.maximum_notional)/reference_price) for x in policies)
    broker={"broker_max_quantity":maximum_quantity,"short_available":target_weight>=0 or all(x.allow_short for x in policies)}
    strategy={"max_weight":min(D(x.maximum_weight) for x in policies)}
    return broker,strategy


@transaction.atomic
def plan_rebalance(portfolio, trigger, idempotency_key, *, prices=None, nav=None, mode=None,
                   policy=None, strict_market_state=True, optimization_run=None, construction_run=None,
                   available_cash=None,defer=False,
                   retry_failed=False):
    if optimization_run and construction_run:
        raise ValueError("A rebalance may use either optimization or goal-construction targets, not both")
    policy = policy or RebalancePolicy.objects.filter(portfolio=portfolio).first() or RebalancePolicy.objects.create(portfolio=portfolio)
    mode = (mode or policy.mode).upper()
    if mode not in {"SHADOW", "PAPER"}:
        raise ValueError("Rebalancing supports SHADOW or PAPER mode only")
    request_hash=canonical_request_hash("rebalance",{
        "portfolio_id":portfolio.pk,"trigger":trigger,"prices":prices,"nav":nav,"mode":mode,
        "policy_id":policy.pk,"strict_market_state":strict_market_state,
        "optimization_run_id":optimization_run.pk if optimization_run else None,
        "construction_run_id":construction_run.pk if construction_run else None,
        "available_cash":available_cash})
    run, created = RebalanceRun.objects.get_or_create(idempotency_key=idempotency_key, defaults={
        "portfolio": portfolio, "policy": policy, "trigger": trigger, "mode": mode,
        "request_hash":request_hash,
        "optimization_run": optimization_run,
        "construction_run": construction_run,
        "target_source": "PORTFOLIO_OPTIMIZATION" if optimization_run else (
            "GOAL_CONSTRUCTION" if construction_run else "STRATEGY_AGGREGATION"
        )})
    if not created:
        require_matching_request(run.request_hash,request_hash)
        if not run.request_hash:
            run.request_hash=request_hash;run.save(update_fields=["request_hash"])
        if run.status=="FAILED" and retry_failed and run.retryable:
            run.targets.all().delete();run.status="QUEUED" if defer else "CALCULATING";run.last_error="";run.retryable=False
            run.attempt_count+=1;run.completed_at=None
            run.save(update_fields=["status","last_error","retryable","attempt_count","completed_at"])
            if defer:return run
        elif run.status!="QUEUED" or defer:return run
        elif run.status=="QUEUED":
            run.status="CALCULATING";run.save(update_fields=["status"])
    elif defer:
        run.status="QUEUED";run.save(update_fields=["status"]);return run
    nav = D(str(nav if nav is not None else portfolio.account.net_liquidation))
    available_cash = D(str(available_cash if available_cash is not None else portfolio.account.available_cash))
    if nav <= 0:
        raise ValueError("Portfolio NAV must be positive")
    current_rows = {x.instrument_id:x for x in PortfolioPosition.objects.filter(portfolio=portfolio).select_related("instrument")}
    if optimization_run:
        if optimization_run.portfolio_id != portfolio.pk or optimization_run.status != "COMPLETED":
            raise ValueError("Optimization run is not a completed target set for this portfolio")
        target_weights = {item.instrument_id: D(item.optimized_weight) for item in optimization_run.targets.all()}
        attribution = {}
    elif construction_run:
        if construction_run.plan.portfolio_id != portfolio.pk or construction_run.status != "COMPLETED":
            raise ValueError("Construction run is not a completed target set for this portfolio")
        target_weights = {item.instrument_id: D(item.target_weight) for item in construction_run.targets.all()}
        attribution = {}
    else:
        target_weights, attribution = aggregate_targets(portfolio)
    instrument_ids = set(target_weights) | set(current_rows)
    reference, unusable = _reference_prices(portfolio, prices or {}, strict_market_state)
    missing = instrument_ids-set(reference)
    if missing:
        raise ValueError(f"No auditable reference price for instruments: {sorted(missing)}")
    run.nav = nav
    run.snapshot = {"nav":str(nav), "cash":str(available_cash), "target_source":run.target_source,
        "optimization_run_id":optimization_run.pk if optimization_run else None,
        "construction_run_id":construction_run.pk if construction_run else None,
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
        elif abs(drift) < D(policy.instrument_drift_threshold) and trigger not in {"MANUAL", "SCHEDULED", "DEPOSIT", "WITHDRAWAL"}: reason = "BELOW_DRIFT_THRESHOLD"
        elif abs(delta) < D(policy.minimum_trade_quantity): reason = "BELOW_MINIMUM_QUANTITY"
        elif notional < D(policy.minimum_trade_notional): reason = "BELOW_MINIMUM_NOTIONAL"
        elif strict_market_state and not hasattr(instrument, "broker_contract"): reason = "UNQUALIFIED_CONTRACT"
        estimated_cost = D(policy.fee_buffer) + notional*VARIABLE_FEE_RATE
        benefit = abs(drift)*nav
        if not reason and estimated_cost >= benefit: reason = "COST_EXCEEDS_BENEFIT"
        candidates.append({"instrument":instrument, "weight":weight, "current":current, "current_weight":current_weight,
            "drift":drift, "target":target_qty, "delta":delta, "price":price, "lot":lot,
            "estimated_cost":estimated_cost, "reason":reason})
    candidates.sort(key=lambda x: (0 if x["delta"]<0 else 1, -abs(x["drift"]), x["estimated_cost"], x["instrument"].pk))
    turnover_used = D(0)
    buy_cash = max(available_cash*(D(1)-D(policy.cash_buffer_percent)), D(0))
    for rank, item in enumerate(candidates):
        item["desired_delta"] = item["delta"]
        if not item["reason"] and item["delta"] > 0:
            affordable = _floor_lot(
                max(buy_cash-D(policy.fee_buffer), D(0))/(item["price"]*(D(1)+VARIABLE_FEE_RATE)),
                item["lot"],
            )
            if affordable < item["delta"]:
                item["delta"] = affordable
            if item["delta"] <= 0:
                item["reason"] = "CASH_OR_FEE_BUFFER"
        trade_turnover = abs(item["delta"]*item["price"])/nav if not item["reason"] else D(0)
        if not item["reason"] and turnover_used+trade_turnover > D(policy.maximum_turnover):
            item["reason"] = "TURNOVER_LIMIT"
        if not item["reason"]:
            turnover_used += trade_turnover
            if item["delta"] < 0 and policy.sell_before_buy:
                sell_notional = abs(item["delta"])*item["price"]
                buy_cash += max(sell_notional-D(policy.fee_buffer)-sell_notional*VARIABLE_FEE_RATE, D(0))
            elif item["delta"] > 0:
                buy_notional = item["delta"]*item["price"]
                buy_cash -= buy_notional+D(policy.fee_buffer)+buy_notional*VARIABLE_FEE_RATE
            item["estimated_cost"] = D(policy.fee_buffer) + abs(item["delta"]*item["price"])*VARIABLE_FEE_RATE
        item["target_row"] = TargetPortfolioPosition.objects.create(rebalance=run, instrument=item["instrument"],
            target_weight=item["weight"], target_quantity=item["target"], trade_quantity=D(0) if item["reason"] else item["delta"],
            reference_price=item["price"], current_quantity=item["current"], current_weight=item["current_weight"],
            drift=item["drift"], lot_size=item["lot"], estimated_cost=item["estimated_cost"],
            suppressed=bool(item["reason"]), suppression_reason=item["reason"], rank=rank)
    planned_has_sells = any(x["delta"] < 0 and not x["reason"] for x in candidates)
    run.total_drift = sum(abs(x["drift"]) for x in candidates)
    run.planned_turnover = turnover_used
    run.phase = "SHADOW_COMPLETE" if mode == "SHADOW" else ("SELLS" if policy.sell_before_buy and planned_has_sells else "BUYS")
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
            contributing_allocations = {
                allocation.strategy_instance_id: allocation
                for allocation in StrategyAllocation.objects.filter(
                    portfolio=portfolio, strategy_instance_id__in=contributions
                ).select_related("strategy_instance")
            }
            for strategy_instance_id in contributions:
                instance=contributing_allocations[strategy_instance_id].strategy_instance
                version=instance.versions.filter(version=instance.version).first()
                if version:version_ids.append(version.pk)
            intent = OrderIntent.objects.create(rebalance=run, portfolio=portfolio, instrument=item["instrument"],
                side="BUY" if is_buy else "SELL", quantity=abs(item["delta"]), reference_price=item["price"],
                order_type=order_type,time_in_force=tif,limit_price=limit_price,strategy_version_snapshot=sorted(version_ids),
                idempotency_key=f"rebalance:{run.pk}:instrument:{item['instrument'].pk}:v1",
                request_hash=canonical_request_hash("strategy_order_intent",{
                    "rebalance_id":run.pk,"portfolio_id":portfolio.pk,"instrument_id":item["instrument"].pk,
                    "side":"BUY" if is_buy else "SELL","quantity":abs(item["delta"]),"order_type":order_type,
                    "time_in_force":tif,"limit_price":limit_price,"strategy_versions":sorted(version_ids)}), source="REBALANCE",
                mode="PAPER", requires_fresh_price=True, execution_priority=item["target_row"].rank, eligible=eligible)
            if strict_market_state:
                from apps.position_sizing.models import PositionSizingPolicy
                from apps.position_sizing.services import size_and_record
                from apps.market_streams.models import IndicatorValue
                sizing_policy = PositionSizingPolicy.objects.filter(portfolio=portfolio, enabled=True).first() or PositionSizingPolicy.objects.create(portfolio=portfolio)
                adv_record = IndicatorValue.objects.filter(instrument=item["instrument"], indicator="average_volume").order_by("-event_time").first()
                broker_limits,strategy_limits=_net_strategy_risk_limits(portfolio,contributions,item["price"],item["weight"])
                size_and_record(sizing_policy, item["instrument"], intent.side, intent.quantity, item["price"], None, nav,
                    available_cash, adv_record.value if adv_record and adv_record.value is not None else 0,
                    broker_limits=broker_limits,strategy_limits=strategy_limits,order_intent=intent,
                    idempotency_key=f"sizing:rebalance:{run.pk}:instrument:{item['instrument'].pk}:v1")
            net_contribution = sum(contributions.values()) or D(1)
            for strategy_instance_id, contribution in contributions.items():
                instance = contributing_allocations[strategy_instance_id].strategy_instance
                OrderIntentAttribution.objects.create(order_intent=intent, strategy_instance=instance,
                    strategy_version=instance.versions.filter(version=instance.version).first(),
                    target_delta=contribution, allocated_quantity=item["delta"]*contribution/net_contribution)
    OutboxEvent.objects.create(topic="portfolio.rebalance.planned.v1", event_type="portfolio.rebalance.planned",
        aggregate_type="portfolio", aggregate_id=str(portfolio.pk), partition_key=str(portfolio.pk),
        payload={"rebalance_run_id":run.pk,"mode":mode,"phase":run.phase,"turnover":str(turnover_used),
                 "target_source":run.target_source,"optimization_run_id":optimization_run.pk if optimization_run else None,
                 "construction_run_id":construction_run.pk if construction_run else None},
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
    fill_ratio=filled/requested if requested else D(1)
    if terminal and fill_ratio < threshold:
        run.phase="BLOCKED"
        run.status="PARTIALLY_COMPLETED" if filled else "FAILED"
        run.last_error=(f"Sell stage ended at fill ratio {fill_ratio}; required threshold is {threshold}. "
            "Buy intents remain ineligible.")
        run.last_recalculated_at=timezone.now()
        run.save(update_fields=["phase","status","last_error","last_recalculated_at"])
        return run
    if requested == 0 or fill_ratio >= threshold:
        portfolio = run.portfolio
        cash = max(D(portfolio.account.available_cash)*(D(1)-D(run.policy.cash_buffer_percent)), D(0))
        positions = {x.instrument_id:D(x.quantity) for x in PortfolioPosition.objects.filter(portfolio=portfolio)}
        turnover_used = sum(
            abs(D(target.trade_quantity) * D(target.reference_price)) / D(run.nav)
            for target in run.targets.filter(trade_quantity__lt=0, suppressed=False)
        )
        for target in run.targets.filter(trade_quantity__gt=0).order_by("rank"):
            intent = OrderIntent.objects.filter(rebalance=run, instrument=target.instrument, side="BUY").first()
            if not intent or hasattr(intent, "order"):
                continue
            desired = max(D(target.target_quantity)-positions.get(target.instrument_id,D(0)),D(0))
            affordable = _floor_lot(
                max(cash-D(run.policy.fee_buffer),D(0))/(D(target.reference_price)*(D(1)+VARIABLE_FEE_RATE)),
                D(target.lot_size),
            )
            turnover_quantity = _floor_lot(
                max(D(run.policy.maximum_turnover)-turnover_used, D(0))*D(run.nav)/D(target.reference_price),
                D(target.lot_size),
            )
            quantity = min(desired, affordable, turnover_quantity)
            if quantity > 0:
                intent.quantity=quantity;intent.eligible=True;intent.save(update_fields=["quantity","eligible"])
                target.trade_quantity=quantity;target.suppressed=False;target.suppression_reason=""
                target.save(update_fields=["trade_quantity","suppressed","suppression_reason"])
                buy_notional = quantity*D(target.reference_price)
                cash -= buy_notional+D(run.policy.fee_buffer)+buy_notional*VARIABLE_FEE_RATE
                turnover_used += quantity*D(target.reference_price)/D(run.nav)
            else:
                target.trade_quantity=0;target.suppressed=True;target.suppression_reason="CASH_OR_FEE_BUFFER"
                if affordable > 0 and turnover_quantity <= 0:
                    target.suppression_reason="TURNOVER_LIMIT"
                target.save(update_fields=["trade_quantity","suppressed","suppression_reason"])
        run.phase = "BUYS"
        run.status = "EXECUTING"
        run.last_error = ""
        run.planned_turnover = turnover_used
        run.last_recalculated_at = timezone.now()
        run.save(update_fields=["phase","status","last_error","planned_turnover","last_recalculated_at"])
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
                    "requires_fresh_price":True,"execution_priority":target.rank,"eligible":True,
                    "request_hash":canonical_request_hash("strategy_order_intent_recovery",{
                        "rebalance_id":run.pk,"instrument_id":target.instrument_id,"side":side,
                        "quantity":remaining,"version":version})})
        recovered += 1
    return recovered
