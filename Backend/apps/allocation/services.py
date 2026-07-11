from decimal import Decimal, ROUND_DOWN
from django.db import transaction
from django.utils import timezone
from apps.audit.models import OutboxEvent
from apps.strategies.models import StrategyAllocation
from .models import AllocationDecision, AllocationRun, PortfolioFlow, StrategyCapitalSnapshot

D = Decimal
CENT = D("0.01")


def _money(value):
    return D(str(value)).quantize(CENT, rounding=ROUND_DOWN)


def allocate_deposit(amount, nav, strategies):
    amount, nav = _money(amount), D(str(nav))
    if amount <= 0:
        raise ValueError("Deposit amount must be positive")
    eligible = [dict(item) for item in strategies if item.get("enabled", True)]
    desired_nav = nav + amount
    for item in eligible:
        current = D(str(item.get("current", 0)))
        share = max(D(str(item["target_share"])), D(str(item.get("minimum_share", 0))))
        item["deficit"] = max(share*desired_nav-current, D(0))
        share_cap = max(D(str(item.get("maximum_share", 1)))*desired_nav-current, D(0))
        capacity_cap = max(D(str(item.get("capacity", desired_nav)))-current, D(0))
        item["cap"] = min(share_cap, capacity_cap)
    weights = [item["deficit"] for item in eligible]
    if sum(weights) == 0:
        weights = [D(str(item["target_share"])) for item in eligible]
    remaining, allocations = amount, {str(item["id"]): D(0) for item in eligible}
    active = list(range(len(eligible)))
    while remaining >= CENT and active:
        denom = sum(weights[i] for i in active)
        if denom <= 0:
            break
        progressed = D(0)
        for i in list(active):
            item, key = eligible[i], str(eligible[i]["id"])
            room = item["cap"] - allocations[key]
            proposed = _money(remaining * weights[i] / denom)
            add = min(room, proposed)
            if add > 0:
                allocations[key] += add; progressed += add
            if room-add < CENT:
                active.remove(i)
        remaining -= progressed
        if progressed < CENT:
            break
    for i in sorted(active, key=lambda x: (eligible[x].get("priority", 100), str(eligible[x]["id"]))):
        key, room = str(eligible[i]["id"]), eligible[i]["cap"]-allocations[str(eligible[i]["id"])]
        add = min(room, remaining)
        allocations[key] += add; remaining -= add
        if remaining < CENT:
            break
    for item in eligible:
        key, minimum = str(item["id"]), D(str(item.get("minimum_allocation", 0)))
        if 0 < allocations[key] < minimum:
            remaining += allocations[key]; allocations[key] = D(0)
    return allocations, _money(remaining), eligible


def allocate_withdrawal(amount, nav, portfolio_cash, strategies, liquidation_policy="PROPORTIONAL"):
    amount, remaining = _money(amount), _money(amount)
    if amount <= 0 or amount >= D(str(nav)):
        raise ValueError("Withdrawal must be positive and less than NAV")
    decisions = []
    cash_take = min(remaining, max(D(str(portfolio_cash)), D(0)))
    if cash_take:
        decisions.append({"strategy_id": None, "source": "PORTFOLIO_CASH", "amount": _money(cash_take)})
        remaining -= cash_take
    ordered = sorted((dict(x) for x in strategies), key=lambda x: (x.get("priority", 100), str(x["id"])))
    for item in ordered:
        take = min(remaining, max(D(str(item.get("idle_cash", 0))), D(0)))
        if take:
            decisions.append({"strategy_id": item["id"], "source": "STRATEGY_CASH", "amount": _money(take)})
            remaining -= take
        if remaining <= 0: break
    desired_nav = D(str(nav))-amount
    surpluses = [(item, max(D(str(item.get("current", 0)))-D(str(item["target_share"]))*desired_nav, D(0))) for item in ordered]
    total = sum(value for _, value in surpluses)
    if remaining > 0 and total > 0:
        original = remaining
        for item, surplus in surpluses:
            take = min(surplus, _money(original*surplus/total), remaining)
            if take:
                decisions.append({"strategy_id": item["id"], "source": "STRATEGY_SURPLUS", "amount": take})
                remaining -= take
    if remaining > 0:
        candidates=[item for item in ordered if D(str(item.get("current",0)))>0]
        if liquidation_policy=="PROPORTIONAL":
            total_capital=sum(D(str(item.get("current",0))) for item in candidates)
            original=remaining
            for item in candidates:
                take=min(remaining,_money(original*D(str(item.get("current",0)))/total_capital)) if total_capital else D(0)
                if take:
                    decisions.append({"strategy_id":item["id"],"source":"POSITION_LIQUIDATION","amount":take,"liquidation_required":True})
                    remaining-=take
            if remaining and candidates:
                decisions[-1]["amount"]+=remaining;remaining=D(0)
        else:
            # Conviction/liquidity/cost inputs are optional policy metadata; priority is the stable fallback.
            metric={"LOWEST_CONVICTION_FIRST":"conviction","MOST_LIQUID_FIRST":"liquidity",
                    "LOWEST_COST_FIRST":"estimated_cost","PRIORITY_ORDER":"priority"}.get(liquidation_policy,"priority")
            reverse=liquidation_policy=="MOST_LIQUID_FIRST"
            candidates.sort(key=lambda item:(D(str(item.get(metric,item.get("priority",100)))),str(item["id"])),reverse=reverse)
            for item in candidates:
                take=min(remaining,D(str(item.get("current",0))))
                if take:
                    decisions.append({"strategy_id":item["id"],"source":"POSITION_LIQUIDATION","amount":_money(take),"liquidation_required":True})
                    remaining-=take
                if remaining<=0:break
        if remaining>0:
            decisions.append({"strategy_id":None,"source":"UNFUNDED","amount":_money(remaining),"liquidation_required":True})
            remaining=D(0)
    return decisions


def _strategy_rows(portfolio):
    rows = []
    for allocation in StrategyAllocation.objects.filter(portfolio=portfolio).select_related("strategy"):
        rows.append({"id": allocation.strategy_id, "enabled": allocation.strategy.enabled and not allocation.strategy.kill_switch,
            "target_share": allocation.weight, "current": allocation.strategy.allocated_capital,
            "minimum_share": allocation.minimum_share, "maximum_share": allocation.maximum_share,
            "capacity": allocation.capacity if allocation.capacity is not None else Decimal("Infinity"),
            "minimum_allocation": allocation.minimum_allocation, "priority": allocation.priority,
            "idle_cash": allocation.idle_cash})
    return rows


@transaction.atomic
def create_flow(portfolio, flow_type, amount, idempotency_key, *, nav=None, effective_at=None,
                liquidation_policy="PROPORTIONAL"):
    if flow_type not in {value for value, _ in PortfolioFlow.TYPES}:
        raise ValueError("Unsupported flow type")
    amount = _money(amount)
    if amount <= 0:
        raise ValueError("Flow amount must be positive")
    flow, created = PortfolioFlow.objects.get_or_create(idempotency_key=idempotency_key, defaults={
        "portfolio": portfolio, "flow_type": flow_type, "amount": amount,
        "currency": portfolio.account.base_currency, "effective_at": effective_at or timezone.now()})
    if not created:
        return flow.allocation_run
    nav = D(str(nav if nav is not None else portfolio.account.net_liquidation))
    cash = D(portfolio.account.available_cash)
    run = AllocationRun.objects.create(flow=flow, portfolio_nav_before=nav, portfolio_cash_before=cash,
        approved_amount=amount, liquidation_policy=liquidation_policy,
        snapshot={"nav": str(nav), "cash": str(cash), "mode": "SHADOW"})
    rows = _strategy_rows(portfolio)
    post_nav = nav + amount if flow_type in {"DEPOSIT", "INTERNAL_TRANSFER_IN"} else nav - amount
    for row in rows:
        target = D(str(row["target_share"]))*post_nav
        current = D(str(row["current"]))
        StrategyCapitalSnapshot.objects.create(allocation_run=run, strategy_id=row["id"], capital_before=current,
            target_capital=target, deficit=max(target-current, 0), surplus=max(current-target, 0), idle_cash=row["idle_cash"])
    if flow_type in {"DEPOSIT", "INTERNAL_TRANSFER_IN"}:
        required_reserve = max(D(portfolio.cash_buffer_pct)*(nav+amount)-cash, D(0))
        investable = max(amount-required_reserve, D(0))
        values, remainder, computed = allocate_deposit(investable, nav, rows) if investable else ({}, D(0), [])
        remainder += amount-investable
        rank = 0
        for row in sorted(computed, key=lambda x: (x.get("priority",100), str(x["id"]))):
            approved = values.get(str(row["id"]), D(0))
            if approved:
                AllocationDecision.objects.create(run=run, strategy_id=row["id"], source="CAPITAL_DEFICIT",
                    requested_amount=amount, approved_amount=approved, rank=rank,
                    binding_constraint="CAPACITY_OR_MAXIMUM" if approved >= row["cap"] else "DEFICIT_WEIGHT",
                    details={"deficit": str(row["deficit"]), "cap": str(row["cap"])})
                rank += 1
        run.unallocated_amount = remainder
    else:
        decisions = allocate_withdrawal(amount, nav, cash, rows, liquidation_policy)
        for rank, item in enumerate(decisions):
            approved=D(0) if item["source"]=="UNFUNDED" else item["amount"]
            if item["source"]=="UNFUNDED":run.unallocated_amount+=item["amount"]
            AllocationDecision.objects.create(run=run, strategy_id=item.get("strategy_id"), source=item["source"],
                requested_amount=item["amount"] if item["source"]=="UNFUNDED" else amount, approved_amount=approved, rank=rank,
                binding_constraint="LIQUIDATION_POLICY" if item.get("liquidation_required") else "AVAILABLE_CAPITAL",
                liquidation_required=item.get("liquidation_required", False))
    strategy_changes={}
    direction=D(1) if flow_type in {"DEPOSIT","INTERNAL_TRANSFER_IN"} else D(-1)
    for decision in run.decisions.exclude(strategy__isnull=True):
        strategy_changes[decision.strategy_id]=strategy_changes.get(decision.strategy_id,D(0))+direction*D(decision.approved_amount)
    from apps.strategies.models import TradingStrategy
    for strategy in TradingStrategy.objects.select_for_update().filter(pk__in=strategy_changes):
        strategy.allocated_capital=max(D(strategy.allocated_capital)+strategy_changes[strategy.pk],D(0))
        strategy.save(update_fields=["allocated_capital"])
    run.approved_amount=amount-run.unallocated_amount
    run.status = "COMPLETED" if run.unallocated_amount==0 else "PARTIALLY_ALLOCATED"
    run.completed_at = timezone.now(); run.save(update_fields=["status", "completed_at", "approved_amount", "unallocated_amount"])
    flow.status = "ALLOCATED"; flow.save(update_fields=["status"])
    OutboxEvent.objects.create(topic="portfolio.flow.allocated.v1", event_type="portfolio.flow.allocated",
        aggregate_type="portfolio", aggregate_id=str(portfolio.pk), partition_key=str(portfolio.pk),
        payload={"flow_id": flow.pk, "allocation_run_id": run.pk, "approved_amount": str(run.approved_amount),
                 "unallocated_amount": str(run.unallocated_amount)}, idempotency_key=f"flow:{flow.pk}:allocated")
    return run


def aggregate_targets(portfolio):
    from apps.rebalancing.services import aggregate_targets as aggregate
    return aggregate(portfolio)[0]


def create_rebalance(portfolio, prices, nav, trigger, idempotency_key):
    from apps.rebalancing.services import plan_rebalance
    return plan_rebalance(portfolio, trigger, idempotency_key, prices=prices, nav=nav, mode="PAPER", strict_market_state=False)
