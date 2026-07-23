import hashlib
import json
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.allocation.models import (
    PortfolioTargetCoordination,
    PortfolioTargetSnapshot,
    RebalancePolicy,
    RebalanceRun,
)
from apps.market_streams.models import InstrumentMarketState
from apps.oms.models import Order, OrderIntent
from apps.portfolios.models import PortfolioPosition, TradingPortfolio
from apps.reconciliation.models import ReconciliationRun
from apps.risk.models import PreTradeRiskPolicy
from apps.strategies.models import (
    StrategyAllocation,
    StrategyAttributedPosition,
    StrategyTarget,
)


D = Decimal
ACTIVE_REBALANCE_STATUSES = {"QUEUED", "CALCULATING", "INTENTS_CREATED", "EXECUTING"}
ACTIVE_ORDER_STATUSES = {
    "CREATED",
    "RISK_APPROVED",
    "QUEUED",
    "BROKER_BLOCKED",
    "SUBMITTED",
    "ACKNOWLEDGED",
    "PARTIALLY_FILLED",
    "CANCEL_PENDING",
    "UNKNOWN",
}
RESERVED_INTENT_STATUSES = {"PENDING", "RISK_APPROVED", "SUBMITTING", "QUEUED"}


def _decimal(value):
    return D(str(value or 0))


def _target_time(target):
    return target.signal_time or target.run.completed_at or target.created_at


def _stable_key(payload):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _latest_targets(allocations):
    instance_ids = [allocation.strategy_instance_id for allocation in allocations]
    selected = {}
    targets = (
        StrategyTarget.objects.filter(
            strategy_instance_id__in=instance_ids,
            run__status="COMPLETED",
            status="ACTIVE",
        )
        .select_related("run", "strategy_version")
        .order_by("strategy_instance_id", "pk")
    )
    for target in targets:
        prior = selected.get(target.strategy_instance_id)
        target_key = (_target_time(target), target.created_at, target.pk)
        prior_key = (_target_time(prior), prior.created_at, prior.pk) if prior else None
        if prior_key is None or target_key > prior_key:
            selected[target.strategy_instance_id] = target
    return selected


def _lifecycle(instance):
    if instance.kill_switch or instance.state == "KILLED":
        return "KILLED"
    if instance.state == "FLATTEN_REQUESTED":
        return "FLATTEN_REQUESTED"
    if instance.state == "PAUSED":
        return "PAUSED"
    if instance.state == "ERROR":
        return "ERROR"
    if instance.state == "DISABLED":
        return "DISABLED"
    if not instance.enabled:
        return "DISABLED"
    return "ACTIVE"


def _lifecycle_policy(instance, lifecycle):
    configuration = instance.risk_policy.configuration if instance.risk_policy_id else {}
    if lifecycle == "FLATTEN_REQUESTED":
        return "FLATTEN"
    if lifecycle == "KILLED":
        return str(configuration.get("killed_behavior", "HOLD")).upper()
    if lifecycle == "ERROR":
        return str(configuration.get("error_behavior", "HOLD")).upper()
    if lifecycle in {"PAUSED", "DISABLED"}:
        return str(configuration.get(f"{lifecycle.lower()}_behavior", "HOLD")).upper()
    return "TARGET"


def _prices(portfolio, instrument_ids, supplied):
    prices = {
        int(key): _decimal(value)
        for key, value in (supplied or {}).items()
        if str(key).isdigit() and _decimal(value) > 0
    }
    states = {
        state.instrument_id: state
        for state in InstrumentMarketState.objects.filter(instrument_id__in=instrument_ids)
    }
    for instrument_id, state in states.items():
        if state.is_usable() and state.reference_price:
            prices[instrument_id] = _decimal(state.reference_price)
    for position in PortfolioPosition.objects.filter(
        portfolio=portfolio, instrument_id__in=instrument_ids
    ):
        if instrument_id := position.instrument_id:
            if instrument_id not in prices and _decimal(position.market_price) > 0:
                prices[instrument_id] = _decimal(position.market_price)
    return prices


def _order_policy_snapshot(allocations, contributions_by_instrument):
    by_instance = {allocation.strategy_instance_id: allocation for allocation in allocations}
    result = {}
    for instrument_id, contributions in contributions_by_instrument.items():
        eligible = sorted(
            (
                by_instance[item["strategy_instance_id"]]
                for item in contributions
                if item["strategy_instance_id"] in by_instance
            ),
            key=lambda allocation: (allocation.priority, allocation.strategy_instance_id),
        )
        selected = next(
            (
                allocation.strategy_instance.order_policy
                for allocation in eligible
                if allocation.strategy_instance.order_policy_id
            ),
            None,
        )
        result[str(instrument_id)] = {
            "owner_strategy_instance_id": next(
                (
                    allocation.strategy_instance_id
                    for allocation in eligible
                    if selected
                    and allocation.strategy_instance.order_policy_id == selected.pk
                ),
                None,
            ),
            "order_type": selected.order_type if selected else "MKT",
            "time_in_force": selected.time_in_force if selected else "DAY",
            "limit_offset_bps": str(selected.limit_offset_bps) if selected else "0",
            "selection_rule": "LOWEST_ALLOCATION_PRIORITY_THEN_STRATEGY_ID",
        }
    return result


def _strategy_limit_error(instance, target, capital, price):
    policy = instance.risk_policy
    if not policy or not policy.enabled:
        return ""
    weight = _decimal(target.target_weight)
    if abs(weight) > _decimal(policy.maximum_weight):
        return "STRATEGY_MAXIMUM_WEIGHT"
    quantity = (
        abs(_decimal(target.target_quantity))
        if target.target_quantity is not None
        else (abs(weight) * capital / price if price > 0 else D(0))
    )
    notional = (
        abs(_decimal(target.target_value))
        if target.target_value is not None
        else quantity * price
    )
    if quantity > _decimal(policy.maximum_quantity):
        return "STRATEGY_MAXIMUM_QUANTITY"
    if notional > _decimal(policy.maximum_notional):
        return "STRATEGY_MAXIMUM_NOTIONAL"
    if weight < 0 and not policy.allow_short:
        return "STRATEGY_SHORT_NOT_ALLOWED"
    return ""


@transaction.atomic
def build_portfolio_target_snapshot(portfolio, *, logical_time=None, prices=None):
    portfolio = (
        TradingPortfolio.objects.select_for_update()
        .select_related("account")
        .get(pk=portfolio.pk)
    )
    account = portfolio.account
    account_nav = _decimal(account.net_liquidation)
    portfolio_nav = account_nav
    available_cash = _decimal(account.available_cash)
    allocations = list(
        StrategyAllocation.objects.filter(portfolio=portfolio)
        .select_related(
            "strategy_instance__risk_policy",
            "strategy_instance__order_policy",
        )
        .order_by("priority", "strategy_instance_id")
    )
    latest = _latest_targets(allocations)
    attributed = list(
        StrategyAttributedPosition.objects.filter(portfolio=portfolio).select_related(
            "strategy_instance"
        )
    )
    positions = list(
        PortfolioPosition.objects.filter(portfolio=portfolio).select_related("instrument")
    )
    active_orders = list(
        Order.objects.filter(
            intent__portfolio=portfolio,
            status__in=ACTIVE_ORDER_STATUSES,
        ).select_related("intent")
    )
    reserved_intents = list(
        OrderIntent.objects.filter(
            portfolio=portfolio,
            operation_status__in=RESERVED_INTENT_STATUSES,
        )
        .filter(Q(order__isnull=True) | ~Q(order__status__in=ACTIVE_ORDER_STATUSES))
        .select_related("instrument", "capital_reservation")
    )
    instrument_ids = {
        *[position.instrument_id for position in positions],
        *[row.instrument_id for row in attributed],
        *[target.instrument_id for target in latest.values()],
        *[order.intent.instrument_id for order in active_orders],
        *[intent.instrument_id for intent in reserved_intents],
    }
    reference_prices = _prices(portfolio, instrument_ids, prices)
    now = timezone.now()
    max_age = int(getattr(settings, "PORTFOLIO_TARGET_MAX_AGE_SECONDS", 900))
    logical_evaluation_time = logical_time or max(
        (_target_time(target) for target in latest.values()),
        default=now,
    )
    target_ages = []
    rejected = [
        {
            "instrument_id": instrument_id,
            "reason": "MISSING_REFERENCE_PRICE",
        }
        for instrument_id in sorted(instrument_ids - set(reference_prices))
    ]
    contributions = []
    contributions_by_instrument = {}
    net_targets = {}
    source_runs = set()
    strategy_versions = {}
    attributed_by_instance = {}
    for row in attributed:
        attributed_by_instance.setdefault(row.strategy_instance_id, []).append(row)

    for allocation in allocations:
        instance = allocation.strategy_instance
        lifecycle = _lifecycle(instance)
        behavior = _lifecycle_policy(instance, lifecycle)
        target = latest.get(instance.pk)
        version = instance.versions.filter(version=instance.version).first()
        strategy_versions[str(instance.pk)] = version.pk if version else None
        if behavior == "TARGET":
            if target is None:
                rejected.append(
                    {
                        "strategy_instance_id": instance.pk,
                        "reason": "MISSING_ACTIVE_TARGET",
                    }
                )
                continue
            event_time = _target_time(target)
            age = max((now - event_time).total_seconds(), 0)
            target_ages.append(
                {
                    "strategy_instance_id": instance.pk,
                    "target_id": target.pk,
                    "event_time": event_time.isoformat(),
                    "age_seconds": age,
                }
            )
            if not version or target.strategy_version_id != version.pk:
                rejected.append(
                    {
                        "strategy_instance_id": instance.pk,
                        "target_id": target.pk,
                        "reason": "INACTIVE_STRATEGY_VERSION",
                    }
                )
                continue
            if age > max_age:
                rejected.append(
                    {
                        "strategy_instance_id": instance.pk,
                        "target_id": target.pk,
                        "reason": "STALE_TARGET",
                        "age_seconds": age,
                    }
                )
                continue
            price = reference_prices.get(target.instrument_id, D(0))
            if price <= 0:
                continue
            capital = (
                _decimal(instance.allocated_capital)
                if _decimal(instance.allocated_capital) > 0
                else account_nav * _decimal(allocation.weight)
            )
            limit_error = _strategy_limit_error(instance, target, capital, price)
            if limit_error:
                rejected.append(
                    {
                        "strategy_instance_id": instance.pk,
                        "target_id": target.pk,
                        "reason": limit_error,
                    }
                )
                continue
            capital_share = capital / account_nav if account_nav > 0 else D(0)
            effective_weight = _decimal(target.target_weight) * capital_share
            current_attributed_quantity = sum(
                (
                    _decimal(row.quantity)
                    for row in attributed_by_instance.get(instance.pk, [])
                    if row.instrument_id == target.instrument_id
                ),
                D(0),
            )
            desired_attributed_quantity = (
                effective_weight * account_nav / price if price > 0 else D(0)
            )
            contribution = {
                "strategy_instance_id": instance.pk,
                "strategy_version_id": version.pk,
                "strategy_version": version.version,
                "strategy_run_id": target.run_id,
                "target_id": target.pk,
                "instrument_id": target.instrument_id,
                "event_time": event_time.isoformat(),
                "age_seconds": age,
                "lifecycle": lifecycle,
                "lifecycle_policy": behavior,
                "target_weight": str(target.target_weight),
                "capital_share": str(capital_share),
                "effective_weight": str(effective_weight),
                "attributed_quantity": str(current_attributed_quantity),
                "desired_attributed_quantity": str(desired_attributed_quantity),
                "strategy_trade_delta": str(
                    desired_attributed_quantity - current_attributed_quantity
                ),
                "risk_result": "APPROVED",
            }
            source_runs.add(target.run_id)
            contributions.append(contribution)
            contributions_by_instrument.setdefault(target.instrument_id, []).append(contribution)
            net_targets[target.instrument_id] = (
                net_targets.get(target.instrument_id, D(0)) + effective_weight
            )
            continue

        lifecycle_target = None
        if lifecycle == "FLATTEN_REQUESTED":
            if target is None:
                rejected.append(
                    {
                        "strategy_instance_id": instance.pk,
                        "reason": "MISSING_FLATTEN_TARGET",
                    }
                )
                continue
            event_time = _target_time(target)
            age = max((now - event_time).total_seconds(), 0)
            target_ages.append(
                {
                    "strategy_instance_id": instance.pk,
                    "target_id": target.pk,
                    "event_time": event_time.isoformat(),
                    "age_seconds": age,
                }
            )
            if not version or target.strategy_version_id != version.pk:
                rejected.append(
                    {
                        "strategy_instance_id": instance.pk,
                        "target_id": target.pk,
                        "reason": "INACTIVE_STRATEGY_VERSION",
                    }
                )
                continue
            if age > max_age:
                rejected.append(
                    {
                        "strategy_instance_id": instance.pk,
                        "target_id": target.pk,
                        "reason": "STALE_TARGET",
                        "age_seconds": age,
                    }
                )
                continue
            lifecycle_target = target
            source_runs.add(target.run_id)

        rows = attributed_by_instance.get(instance.pk, [])
        if behavior not in {"HOLD", "FLATTEN"}:
            rejected.append(
                {
                    "strategy_instance_id": instance.pk,
                    "reason": f"INVALID_{lifecycle}_POLICY",
                    "policy": behavior,
                }
            )
            continue
        instrument_rows = rows or [None]
        for row in instrument_rows:
            instrument_id = row.instrument_id if row else instance.instrument_id
            price = reference_prices.get(instrument_id, D(0))
            quantity = _decimal(row.quantity) if row and behavior == "HOLD" else D(0)
            effective_weight = quantity * price / account_nav if account_nav > 0 else D(0)
            current_attributed_quantity = _decimal(row.quantity) if row else D(0)
            contribution = {
                "strategy_instance_id": instance.pk,
                "strategy_version_id": version.pk if version else None,
                "strategy_version": version.version if version else instance.version,
                "strategy_run_id": lifecycle_target.run_id if lifecycle_target else None,
                "target_id": lifecycle_target.pk if lifecycle_target else None,
                "instrument_id": instrument_id,
                "event_time": (
                    _target_time(lifecycle_target).isoformat()
                    if lifecycle_target
                    else logical_evaluation_time.isoformat()
                ),
                "age_seconds": 0,
                "lifecycle": lifecycle,
                "lifecycle_policy": behavior,
                "target_weight": None,
                "capital_share": None,
                "effective_weight": str(effective_weight),
                "attributed_quantity": str(current_attributed_quantity),
                "desired_attributed_quantity": str(quantity),
                "strategy_trade_delta": str(quantity - current_attributed_quantity),
                "risk_result": "APPROVED",
            }
            contributions.append(contribution)
            contributions_by_instrument.setdefault(instrument_id, []).append(contribution)
            net_targets[instrument_id] = (
                net_targets.get(instrument_id, D(0)) + effective_weight
            )

    signed_open = {}
    open_orders = []
    for order in active_orders:
        remaining = max(_decimal(order.quantity) - _decimal(order.filled_quantity), D(0))
        signed = remaining if order.intent.side == "BUY" else -remaining
        signed_open[order.intent.instrument_id] = (
            signed_open.get(order.intent.instrument_id, D(0)) + signed
        )
        open_orders.append(
            {
                "order_id": order.pk,
                "order_intent_id": order.intent_id,
                "instrument_id": order.intent.instrument_id,
                "side": order.intent.side,
                "status": order.status,
                "quantity": str(order.quantity),
                "filled_quantity": str(order.filled_quantity),
                "remaining_signed_quantity": str(signed),
            }
        )
    signed_reserved = {}
    exposure_reservations = []
    for intent in reserved_intents:
        signed = _decimal(intent.quantity) if intent.side == "BUY" else -_decimal(intent.quantity)
        signed_reserved[intent.instrument_id] = (
            signed_reserved.get(intent.instrument_id, D(0)) + signed
        )
        exposure_reservations.append(
            {
                "order_intent_id": intent.pk,
                "instrument_id": intent.instrument_id,
                "side": intent.side,
                "operation_status": intent.operation_status,
                "reserved_signed_quantity": str(signed),
                "capital_reservation_amount": (
                    str(intent.capital_reservation.amount)
                    if hasattr(intent, "capital_reservation")
                    else "0"
                ),
            }
        )
    position_map = {}
    position_by_instrument = {position.instrument_id: position for position in positions}
    for instrument_id in instrument_ids:
        filled = _decimal(
            position_by_instrument[instrument_id].quantity
            if instrument_id in position_by_instrument
            else 0
        )
        projected = (
            filled
            + signed_open.get(instrument_id, D(0))
            + signed_reserved.get(instrument_id, D(0))
        )
        position_map[str(instrument_id)] = {
            "filled_quantity": str(filled),
            "remaining_signed_broker_orders": str(
                signed_open.get(instrument_id, D(0))
            ),
            "reserved_signed_order_intents": str(
                signed_reserved.get(instrument_id, D(0))
            ),
            "projected_quantity": str(projected),
        }

    order_policy = _order_policy_snapshot(allocations, contributions_by_instrument)
    pre_trade, _ = PreTradeRiskPolicy.objects.get_or_create(portfolio=portfolio)
    portfolio_limits = {
        "policy_id": pre_trade.pk,
        "version": pre_trade.version,
        "enabled": pre_trade.enabled,
        "maximum_order_quantity": str(pre_trade.maximum_order_quantity),
        "maximum_order_notional": str(pre_trade.maximum_order_notional),
    }
    rebalance_policy = RebalancePolicy.objects.filter(portfolio=portfolio).first()
    contributing_modes = {
        allocation.strategy_instance.execution_mode
        for allocation in allocations
        if any(
            item["strategy_instance_id"] == allocation.strategy_instance_id
            for item in contributions
        )
    }
    execution_mode = (
        "SHADOW"
        if "SHADOW" in contributing_modes
        else str(rebalance_policy.mode if rebalance_policy else "SHADOW").upper()
    )
    if execution_mode not in {"SHADOW", "PAPER"}:
        execution_mode = "SHADOW"
    reconciliation = (
        ReconciliationRun.objects.filter(
            broker_account=account,
            status="COMPLETED",
        )
        .order_by("-completed_at", "-pk")
        .first()
    )
    generation = str(reconciliation.pk) if reconciliation else ""
    status = "REJECTED" if rejected or account_nav <= 0 else "READY"
    payload = {
        "portfolio_id": portfolio.pk,
        "logical_evaluation_time": logical_evaluation_time.isoformat(),
        "source_strategy_runs": sorted(source_runs),
        "strategy_versions": strategy_versions,
        "target_contributions": contributions,
        "target_ages": target_ages,
        "net_targets": {str(key): str(value) for key, value in net_targets.items()},
        "account_nav": str(account_nav),
        "portfolio_nav": str(portfolio_nav),
        "available_cash": str(available_cash),
        "current_positions": position_map,
        "open_orders": open_orders,
        "exposure_reservations": exposure_reservations,
        "reference_prices": {
            str(key): str(value) for key, value in reference_prices.items()
        },
        "broker_reconciliation_generation": generation,
        "execution_mode": execution_mode,
        "portfolio_order_policy": order_policy,
        "portfolio_risk_limits": portfolio_limits,
        "rejected_targets": rejected,
        "status": status,
    }
    idempotency_key = f"portfolio-target:{portfolio.pk}:{_stable_key(payload)}"
    snapshot, _ = PortfolioTargetSnapshot.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "portfolio": portfolio,
            "logical_evaluation_time": logical_evaluation_time,
            "source_strategy_runs": sorted(source_runs),
            "strategy_versions": strategy_versions,
            "target_contributions": contributions,
            "target_ages": target_ages,
            "net_targets": payload["net_targets"],
            "account_nav": account_nav,
            "portfolio_nav": portfolio_nav,
            "available_cash": available_cash,
            "current_positions": position_map,
            "open_orders": open_orders,
            "exposure_reservations": exposure_reservations,
            "reference_prices": payload["reference_prices"],
            "broker_reconciliation_generation": generation,
            "execution_mode": execution_mode,
            "portfolio_order_policy": order_policy,
            "portfolio_risk_limits": portfolio_limits,
            "rejected_targets": rejected,
            "status": status,
        },
    )
    return snapshot


@transaction.atomic
def mark_portfolio_for_target_coordination(portfolio_id, *, logical_event_time=None):
    now = timezone.now()
    debounce_seconds = int(
        getattr(settings, "PORTFOLIO_TARGET_COORDINATION_DEBOUNCE_SECONDS", 2)
    )
    coordination, _ = PortfolioTargetCoordination.objects.select_for_update().get_or_create(
        portfolio_id=portfolio_id
    )
    active = RebalanceRun.objects.filter(
        portfolio_id=portfolio_id,
        automatic=True,
        status__in=ACTIVE_REBALANCE_STATUSES,
    ).first()
    if (
        active
        and logical_event_time
        and coordination.logical_event_time
        and logical_event_time <= coordination.logical_event_time
    ):
        return coordination
    coordination.needs_coordination = True
    coordination.requested_at = now
    coordination.logical_event_time = max(
        filter(
            None,
            [coordination.logical_event_time, logical_event_time],
        ),
        default=logical_event_time or now,
    )
    if active:
        coordination.pending_recalculation = True
        coordination.active_rebalance = active
        coordination.status = "ACTIVE"
    else:
        coordination.status = "PENDING"
        coordination.debounce_until = now + timedelta(seconds=debounce_seconds)
    coordination.last_error = ""
    coordination.save()
    return coordination


@transaction.atomic
def coordinate_portfolio(portfolio_id):
    portfolio = (
        TradingPortfolio.objects.select_for_update()
        .select_related("account")
        .get(pk=portfolio_id)
    )
    coordination, _ = PortfolioTargetCoordination.objects.select_for_update().get_or_create(
        portfolio=portfolio
    )
    active = (
        RebalanceRun.objects.filter(
            portfolio=portfolio,
            automatic=True,
            status__in=ACTIVE_REBALANCE_STATUSES,
        )
        .order_by("created_at")
        .first()
    )
    if active:
        if coordination.needs_coordination:
            coordination.pending_recalculation = True
        coordination.active_rebalance = active
        coordination.status = "ACTIVE"
        coordination.save()
        return active
    snapshot = build_portfolio_target_snapshot(
        portfolio,
        logical_time=coordination.logical_event_time,
    )
    coordination.last_snapshot = snapshot
    coordination.needs_coordination = False
    coordination.pending_recalculation = False
    if snapshot.status != "READY":
        coordination.status = "ERROR"
        coordination.last_error = "Portfolio target snapshot rejected one or more inputs"
        coordination.active_rebalance = None
        coordination.save()
        return snapshot
    from apps.rebalancing.services import plan_rebalance

    run = plan_rebalance(
        portfolio,
        "STRATEGY_TARGETS",
        f"rebalance:{snapshot.idempotency_key}",
        target_snapshot=snapshot,
        mode=snapshot.execution_mode,
        automatic=True,
    )
    if run.status in ACTIVE_REBALANCE_STATUSES:
        coordination.status = "ACTIVE"
        coordination.active_rebalance = run
    else:
        coordination.status = "IDLE"
        coordination.active_rebalance = None
    coordination.last_error = ""
    coordination.save()
    return run


def process_target_coordination(limit=None):
    limit = int(limit or getattr(settings, "PORTFOLIO_TARGET_COORDINATION_BATCH_SIZE", 50))
    now = timezone.now()
    with transaction.atomic():
        rows = list(
            PortfolioTargetCoordination.objects.select_for_update(skip_locked=True)
            .filter(needs_coordination=True)
            .filter(Q(debounce_until__isnull=True) | Q(debounce_until__lte=now))
            .exclude(status="ACTIVE")
            .order_by("requested_at", "pk")[:limit]
        )
        portfolio_ids = [row.portfolio_id for row in rows]
        PortfolioTargetCoordination.objects.filter(pk__in=[row.pk for row in rows]).update(
            status="CLAIMED"
        )
    results = []
    for portfolio_id in portfolio_ids:
        try:
            result = coordinate_portfolio(portfolio_id)
            results.append({"portfolio_id": portfolio_id, "result_id": result.pk})
        except Exception as exc:
            PortfolioTargetCoordination.objects.filter(portfolio_id=portfolio_id).update(
                status="ERROR",
                needs_coordination=True,
                last_error=str(exc)[:1000],
            )
            raise
    return results


@transaction.atomic
def release_portfolio_coordination(run):
    if not run.automatic:
        return
    coordination = PortfolioTargetCoordination.objects.select_for_update().filter(
        portfolio_id=run.portfolio_id
    ).first()
    if not coordination:
        return
    if coordination.active_rebalance_id == run.pk:
        coordination.active_rebalance = None
    if coordination.pending_recalculation:
        coordination.needs_coordination = True
        coordination.pending_recalculation = False
        coordination.status = "PENDING"
        coordination.debounce_until = timezone.now()
    else:
        coordination.needs_coordination = False
        coordination.status = "IDLE"
    coordination.save()
