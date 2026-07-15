from decimal import Decimal, ROUND_DOWN

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.models import AuditEvent, OperationAttempt, OutboxEvent
from apps.core.idempotency import canonical_request_hash, require_matching_request
from apps.instruments.models import Instrument
from apps.market_data.models import InstrumentPriceHistory
from apps.portfolio_optimization.services import (
    OptimizationError,
    calculate_weighted_metrics,
    optimize_explicit_universe,
)
from apps.portfolios.models import PortfolioPosition
from apps.strategies.models import StrategyDefinition, StrategyInstance
from apps.strategies.plugins import get_plugin

from .models import (
    GoalStrategySelection,
    PortfolioConstructionPlan,
    PortfolioConstructionRun,
    PortfolioConstructionTarget,
    StrategyConstructionProfile,
)
from .rules import resolved_goal_rules, validate_timeframe_risk


D = Decimal
WEIGHT_QUANTUM = D("0.00000001")


class ConstructionError(ValueError):
    pass


class ConstructionAlreadyApplied(ConstructionError):
    code = "CONSTRUCTION_ALREADY_APPLIED"

    def __init__(self, construction_run):
        self.construction_run = construction_run
        super().__init__(
            f"Construction run {construction_run.pk} was already applied by rebalance "
            f"{construction_run.applied_rebalance_id}"
        )


def decimal_string(value):
    return format(D(str(value)), "f")


def bump_plan_version(plan):
    PortfolioConstructionPlan.objects.filter(pk=plan.pk).update(version=F("version") + 1, updated_at=timezone.now())
    plan.refresh_from_db(fields=["version", "updated_at"])
    return plan


def plan_validation(plan):
    goals = list(plan.goals.filter(enabled=True).order_by("display_order", "pk"))
    total = sum((D(goal.allocation_weight) for goal in goals), D(0))
    errors = []
    if not goals:
        errors.append({"code": "NO_ENABLED_GOALS", "message": "At least one goal must be enabled"})
    if len(goals) > 10:
        errors.append({"code": "TOO_MANY_GOALS", "message": "At most ten goals may be enabled"})
    if total != D(1):
        errors.append({
            "code": "ALLOCATION_TOTAL",
            "message": "Enabled goal allocations must total exactly 100%",
            "allocated_weight": decimal_string(total),
        })
    for goal in goals:
        try:
            validate_timeframe_risk(goal.timeframe_bucket, goal.risk_level)
        except ValueError as exc:
            errors.append({"code": "INVALID_GOAL_RULES", "goal_id": goal.pk, "message": str(exc)})
    return {
        "allocated_weight": total,
        "allocated_percentage": total * D(100),
        "enabled_goal_count": len(goals),
        "ready_to_preview": not errors,
        "validation_errors": errors,
    }


def require_plan_ready(plan):
    validation = plan_validation(plan)
    if validation["validation_errors"]:
        raise ConstructionError("; ".join(item["message"] for item in validation["validation_errors"]))
    return validation


def strategy_eligibility(definition, goal):
    reasons = []
    profile = StrategyConstructionProfile.objects.filter(strategy_definition=definition).first()
    plugin = None
    try:
        plugin = get_plugin(definition)
    except Exception:
        reasons.append("Strategy implementation is unavailable")
    if not definition.enabled:
        reasons.append("Strategy is disabled")
    if not profile:
        reasons.append("No construction profile is configured")
    else:
        if not profile.construction_enabled:
            reasons.append("Strategy is disabled for portfolio construction")
        if not profile.user_selectable:
            reasons.append("Strategy is not user-selectable")
        if goal.timeframe_bucket not in profile.supported_goal_timeframes:
            reasons.append(f"Strategy does not support {goal.timeframe_bucket} goals")
        if not profile.minimum_risk <= goal.risk_level <= profile.maximum_risk:
            reasons.append(f"Strategy supports risk levels {profile.minimum_risk}-{profile.maximum_risk}")
    if goal.timeframe_bucket == "NOW":
        reasons.append("NOW goals are intentionally cash-only")
    if "STK" not in definition.supported_asset_types:
        reasons.append("Strategy does not support stocks")
    if "LONG" not in definition.supported_directions:
        reasons.append("Strategy cannot operate long-only")
    if not definition.supported_timeframes:
        reasons.append("Strategy has no supported market-data timeframe")
    return {
        "strategy_definition_id": definition.pk,
        "key": definition.key,
        "name": definition.name,
        "summary": profile.summary if profile else definition.description,
        "limitations": profile.limitations if profile else "",
        "execution_timeframes": definition.supported_timeframes,
        "default_parameters": plugin.default_parameters if plugin else {},
        "parameter_schema": definition.parameter_schema,
        "eligible": not reasons,
        "reason": "; ".join(reasons),
    }


def eligible_strategies(goal):
    rows = [strategy_eligibility(item, goal) for item in StrategyDefinition.objects.all().order_by("name")]
    return {
        "goal_id": goal.pk,
        "eligible": [item for item in rows if item["eligible"]],
        "rejected": [item for item in rows if not item["eligible"]],
    }


def validate_selection(*, goal, definition, instrument, execution_timeframe, parameter_overrides):
    eligibility = strategy_eligibility(definition, goal)
    if not eligibility["eligible"]:
        raise ConstructionError(eligibility["reason"])
    if not instrument.active or not instrument.tradable or instrument.asset_class != "STK":
        raise ConstructionError("Instrument must be an active, tradable stock")
    if execution_timeframe not in definition.supported_timeframes:
        raise ConstructionError(f"Unsupported execution timeframe {execution_timeframe}")
    if not isinstance(parameter_overrides, dict):
        raise ConstructionError("parameter_overrides must be an object")
    try:
        parameters = get_plugin(definition).validate_configuration(parameter_overrides, {})
    except ValueError as exc:
        raise ConstructionError(str(exc)) from exc
    if parameters.get("direction", "LONG") != "LONG":
        raise ConstructionError("Portfolio Builder selections must be long-only")
    return parameters


def _selection_snapshot(selection):
    return {
        "id": selection.pk,
        "goal_id": selection.goal_allocation_id,
        "strategy_definition_id": selection.strategy_definition_id,
        "strategy_key": selection.strategy_definition.key,
        "strategy_name": selection.strategy_definition.name,
        "instrument_id": selection.instrument_id,
        "symbol": selection.instrument.symbol,
        "execution_timeframe": selection.execution_timeframe,
        "parameter_overrides": selection.parameter_overrides,
        "enabled": selection.enabled,
    }


def snapshot_plan(plan):
    require_plan_ready(plan)
    goals = list(plan.goals.filter(enabled=True).order_by("display_order", "pk"))
    goal_rows = []
    selection_rows = []
    policy_rows = {}
    for goal in goals:
        rules = resolved_goal_rules(goal.timeframe_bucket, goal.risk_level)
        goal_rows.append({
            "id": goal.pk,
            "name": goal.name,
            "allocation_weight": decimal_string(goal.allocation_weight),
            "timeframe_bucket": goal.timeframe_bucket,
            "risk_level": goal.risk_level,
            "display_order": goal.display_order,
        })
        policy_rows[str(goal.pk)] = {
            key: decimal_string(value) if isinstance(value, D) else value for key, value in rules.items()
        }
        for selection in goal.selections.filter(enabled=True).select_related("strategy_definition", "instrument"):
            # Revalidate mutable definitions and profiles at the snapshot boundary.
            validate_selection(
                goal=goal,
                definition=selection.strategy_definition,
                instrument=selection.instrument,
                execution_timeframe=selection.execution_timeframe,
                parameter_overrides=selection.parameter_overrides,
            )
            selection_rows.append(_selection_snapshot(selection))
    return {
        "plan": {
            "id": plan.pk,
            "portfolio_id": plan.portfolio_id,
            "name": plan.name,
            "status": plan.status,
            "version": plan.version,
        },
        "goals": goal_rows,
        "selections": selection_rows,
        "policies": policy_rows,
    }


def create_construction_run(
    plan,
    idempotency_key,
    *,
    nav=None,
    refresh_history=True,
    retry_failed=False,
    defer=False,
):
    snapshot = snapshot_plan(plan)
    nav = D(str(nav if nav is not None else plan.portfolio.account.net_liquidation))
    if nav <= 0:
        raise ConstructionError("Portfolio NAV must be positive")
    request_hash = canonical_request_hash("portfolio_construction", {
        "plan_id": plan.pk,
        "plan_version": plan.version,
        "nav": nav,
        "refresh_history": refresh_history,
    })
    existing = PortfolioConstructionRun.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        try:
            require_matching_request(existing.request_hash, request_hash)
        except ValueError as exc:
            raise ConstructionError(str(exc)) from exc
        if existing.status != "FAILED" or not retry_failed:
            return existing
        if not existing.retryable:
            raise ConstructionError("Failed construction preview is not retryable")
        with transaction.atomic():
            run = PortfolioConstructionRun.objects.select_for_update().get(pk=existing.pk)
            run.targets.all().delete()
            run.status = "QUEUED" if defer else "CALCULATING"
            run.retryable = False
            run.last_error = ""
            run.goal_results = []
            run.final_target_weights = {}
            run.metrics = {}
            run.warnings = []
            run.started_at = None
            run.completed_at = None
            run.attempt_count += 1
            run.save()
            OperationAttempt.objects.create(
                operation_type="PORTFOLIO_CONSTRUCTION",
                operation_id=str(run.pk),
                attempt_number=run.attempt_count,
                request_hash=run.request_hash,
                status="QUEUED" if defer else "PROCESSING",
            )
        return run
    run = PortfolioConstructionRun.objects.create(
        plan=plan,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        status="QUEUED" if defer else "CALCULATING",
        nav=nav,
        plan_snapshot=snapshot["plan"],
        goal_snapshot=snapshot["goals"],
        selection_snapshot=snapshot["selections"],
        policy_snapshot=snapshot["policies"],
    )
    OperationAttempt.objects.create(
        operation_type="PORTFOLIO_CONSTRUCTION",
        operation_id=str(run.pk),
        attempt_number=run.attempt_count,
        request_hash=run.request_hash,
        status="QUEUED" if defer else "PROCESSING",
    )
    return run


def _quantize_weight(value):
    return D(str(value)).quantize(WEIGHT_QUANTUM, rounding=ROUND_DOWN)


def _metric_strings(metrics):
    return {
        "expected_return": decimal_string(metrics.get("expected_return", 0)),
        "expected_volatility": decimal_string(metrics.get("expected_volatility", 0)),
        "sharpe_ratio": decimal_string(metrics.get("sharpe_ratio", 0)),
    }


def _single_stock_metrics(instruments, weights, refresh_history):
    try:
        return calculate_weighted_metrics(
            instruments,
            weights,
            lookback_days=252,
            minimum_history_observations=60,
            refresh_history=refresh_history,
        )
    except OptimizationError as exc:
        return {
            "expected_return": 0,
            "expected_volatility": 0,
            "sharpe_ratio": 0,
            "expected_return_contributions": {},
            "risk_contributions": {},
            "warnings": [{"code": "METRICS_UNAVAILABLE", "message": str(exc)}],
        }


def run_construction(construction_run, *, refresh_history=True):
    run_id = construction_run.pk if isinstance(construction_run, PortfolioConstructionRun) else construction_run
    run = PortfolioConstructionRun.objects.select_related("plan__portfolio__account").get(pk=run_id)
    if run.status == "COMPLETED":
        return run
    if run.status not in {"QUEUED", "DISPATCHED", "CALCULATING"}:
        return run
    run.status = "CALCULATING"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])
    OperationAttempt.objects.filter(
        operation_type="PORTFOLIO_CONSTRUCTION",
        operation_id=str(run.pk),
        attempt_number=run.attempt_count,
        status="QUEUED",
    ).update(status="PROCESSING")
    try:
        selections_by_goal = {}
        for selection in run.selection_snapshot:
            if selection.get("enabled", True):
                selections_by_goal.setdefault(int(selection["goal_id"]), []).append(selection)
        goal_results = []
        combined = {}
        combined_contributions = {}
        all_warnings = []
        instruments_by_id = {
            item.pk: item
            for item in Instrument.objects.filter(
                pk__in={int(item["instrument_id"]) for item in run.selection_snapshot},
                active=True,
                tradable=True,
                asset_class="STK",
            )
        }
        for goal in run.goal_snapshot:
            goal_id = int(goal["id"])
            allocation = D(goal["allocation_weight"])
            rules = run.policy_snapshot[str(goal_id)]
            minimum_cash = D(rules["minimum_cash_weight"])
            maximum_stock = D(rules["maximum_stock_weight"])
            selections = selections_by_goal.get(goal_id, [])
            instrument_ids = sorted({int(item["instrument_id"]) for item in selections})
            instruments = [instruments_by_id[item_id] for item_id in instrument_ids if item_id in instruments_by_id]
            warnings = []
            apply_blocked = False
            local_weights = {}
            metrics = {
                "expected_return": 0,
                "expected_volatility": 0,
                "sharpe_ratio": 0,
                "expected_return_contributions": {},
                "risk_contributions": {},
                "warnings": [],
            }
            if goal["timeframe_bucket"] == "NOW":
                cash_weight = D(1)
            elif not instruments:
                cash_weight = D(1)
                apply_blocked = True
                warnings.append({
                    "code": "NO_STOCKS_SELECTED",
                    "message": "No stocks are selected; preview is cash-only and apply is blocked for this goal",
                })
            elif len(instruments) == 1:
                stock_weight = min(D(1) - minimum_cash, maximum_stock)
                local_weights[instruments[0].pk] = stock_weight
                cash_weight = D(1) - stock_weight
                if stock_weight < D(1) - minimum_cash:
                    warnings.append({
                        "code": "SINGLE_STOCK_LIMIT",
                        "message": "The single selected stock was capped and the unused allocation remains cash",
                    })
                metrics = _single_stock_metrics(instruments, local_weights, refresh_history)
            else:
                stock_total = min(D(1) - minimum_cash, maximum_stock * len(instruments))
                cash_weight = D(1) - stock_total
                solved = optimize_explicit_universe(
                    instruments,
                    method=rules["optimizer_method"],
                    cash_weight=cash_weight,
                    maximum_weight=maximum_stock,
                    lookback_days=int(rules["lookback_days"]),
                    minimum_history_observations=int(rules["minimum_history_observations"]),
                    maximum_turnover=10,
                    transaction_cost_penalty=0,
                    risk_free_rate=0,
                    long_only=True,
                    refresh_history=refresh_history,
                )
                local_weights = {
                    instrument_id: _quantize_weight(solved["weights"][index])
                    for index, instrument_id in enumerate(solved["instrument_ids"])
                }
                cash_weight = D(1) - sum(local_weights.values(), D(0))
                metrics = solved
            warnings.extend(metrics.get("warnings", []))
            stocks = []
            for instrument_id, local_weight in sorted(local_weights.items(), key=lambda item: (-item[1], item[0])):
                contribution = allocation * local_weight
                combined[instrument_id] = combined.get(instrument_id, D(0)) + contribution
                contribution_row = {
                    "goal_id": goal_id,
                    "goal_name": goal["name"],
                    "goal_allocation_weight": decimal_string(allocation),
                    "local_weight": decimal_string(local_weight),
                    "portfolio_contribution": decimal_string(contribution),
                }
                combined_contributions.setdefault(instrument_id, []).append(contribution_row)
                stocks.append({
                    "instrument_id": instrument_id,
                    "symbol": instruments_by_id[instrument_id].symbol,
                    **contribution_row,
                })
            result = {
                "goal_id": goal_id,
                "name": goal["name"],
                "allocation_weight": decimal_string(allocation),
                "goal_nav": decimal_string(run.nav * allocation),
                "timeframe_bucket": goal["timeframe_bucket"],
                "risk_level": goal["risk_level"],
                "optimizer_method": rules["optimizer_method"],
                "cash_weight": decimal_string(cash_weight),
                "maximum_stock_weight": decimal_string(maximum_stock),
                "stocks": stocks,
                "metrics": _metric_strings(metrics),
                "warnings": warnings,
                "intentionally_cash_only": goal["timeframe_bucket"] == "NOW",
                "apply_blocked": apply_blocked,
            }
            goal_results.append(result)
            all_warnings.extend({**warning, "goal_id": goal_id, "goal_name": goal["name"]} for warning in warnings)
        combined = {key: _quantize_weight(value) for key, value in combined.items() if value > 0}
        cash_weight = D(1) - sum(combined.values(), D(0))
        if cash_weight < 0 or sum(combined.values(), D(0)) + cash_weight != D(1):
            raise ConstructionError("Combined stock and cash weights must equal 100%")
        final_instruments = [instruments_by_id[key] for key in combined]
        combined_metrics = _single_stock_metrics(final_instruments, combined, refresh_history)
        all_warnings.extend(combined_metrics.get("warnings", []))
        positions = {
            item.instrument_id: D(item.quantity) * D(item.market_price) / D(run.nav)
            for item in PortfolioPosition.objects.filter(portfolio=run.plan.portfolio)
            if D(item.market_price) > 0
        }
        with transaction.atomic():
            run.targets.all().delete()
            for rank, (instrument_id, target_weight) in enumerate(sorted(combined.items(), key=lambda item: (-item[1], item[0]))):
                PortfolioConstructionTarget.objects.create(
                    construction_run=run,
                    instrument=instruments_by_id[instrument_id],
                    current_weight=positions.get(instrument_id, D(0)),
                    target_weight=target_weight,
                    target_value=target_weight * D(run.nav),
                    expected_return_contribution=D(str(combined_metrics.get("expected_return_contributions", {}).get(instrument_id, 0))),
                    risk_contribution=D(str(combined_metrics.get("risk_contributions", {}).get(instrument_id, 0))),
                    goal_contributions=combined_contributions[instrument_id],
                    rank=rank,
                )
            run.goal_results = goal_results
            run.final_target_weights = {
                "cash": decimal_string(cash_weight),
                "stocks": {str(key): decimal_string(value) for key, value in combined.items()},
            }
            run.metrics = _metric_strings(combined_metrics)
            run.warnings = all_warnings
            run.status = "COMPLETED"
            run.retryable = False
            run.last_error = ""
            run.completed_at = timezone.now()
            run.save()
            OperationAttempt.objects.filter(
                operation_type="PORTFOLIO_CONSTRUCTION",
                operation_id=str(run.pk),
                attempt_number=run.attempt_count,
            ).update(status="COMPLETED", result={"construction_run_id": run.pk}, completed_at=run.completed_at)
            OutboxEvent.objects.create(
                topic="portfolio.construction.completed.v1",
                event_type="portfolio.construction.completed",
                aggregate_type="portfolio",
                aggregate_id=str(run.plan.portfolio_id),
                partition_key=str(run.plan.portfolio_id),
                payload={"construction_run_id": run.pk, "plan_id": run.plan_id},
                idempotency_key=f"construction:{run.pk}:attempt:{run.attempt_count}:completed",
            )
            AuditEvent.objects.create(
                event_type="portfolio.construction.completed",
                actor="system",
                aggregate_type="portfolio",
                aggregate_id=str(run.plan.portfolio_id),
                data={"construction_run_id": run.pk, "plan_id": run.plan_id, "plan_version": run.plan_snapshot["version"]},
                idempotency_key=f"audit:construction:{run.pk}:attempt:{run.attempt_count}:completed",
            )
        return run
    except Exception as exc:
        run.status = "FAILED"
        run.last_error = str(exc)[:1000]
        run.retryable = not isinstance(exc, (ConstructionError, OptimizationError, ValueError))
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "last_error", "retryable", "completed_at"])
        OperationAttempt.objects.filter(
            operation_type="PORTFOLIO_CONSTRUCTION",
            operation_id=str(run.pk),
            attempt_number=run.attempt_count,
        ).update(status="FAILED", retryable=run.retryable, error=run.last_error, completed_at=run.completed_at)
        if isinstance(exc, ConstructionError):
            raise
        raise ConstructionError(str(exc)) from exc


def latest_prices(construction_run):
    result = {}
    for target in construction_run.targets.select_related("instrument"):
        price = InstrumentPriceHistory.objects.filter(
            instrument=target.instrument, provider="FINNHUB"
        ).order_by("-trading_date").first()
        if not price:
            raise ConstructionError(f"No historical reference price is available for {target.instrument.symbol}")
        result[target.instrument_id] = price.adjusted_close or price.close
    for position in PortfolioPosition.objects.filter(portfolio=construction_run.plan.portfolio):
        if position.instrument_id not in result and position.market_price > 0:
            result[position.instrument_id] = position.market_price
    return result


def plan_construction_rebalance(construction_run, idempotency_key, *, mode="SHADOW", strict_market_state=False):
    if construction_run.status != "COMPLETED":
        raise ConstructionError("Only a completed construction run can create rebalance targets")
    from apps.rebalancing.services import plan_rebalance

    return plan_rebalance(
        construction_run.plan.portfolio,
        "GOAL_CONSTRUCTION",
        idempotency_key,
        prices=latest_prices(construction_run),
        nav=construction_run.nav,
        mode=mode,
        strict_market_state=strict_market_state,
        construction_run=construction_run,
    )


def _instance_name(run, selection, suffix=0):
    base = f"Builder {selection['strategy_name']} {selection['symbol']} {selection['execution_timeframe']}"
    if suffix:
        base = f"{base} {suffix}"
    return base[:128]


def create_or_reuse_strategy_instances(run):
    from apps.strategies.framework import create_instance

    linked = []
    cache = {}
    for selection in run.selection_snapshot:
        identity = (
            int(selection["strategy_definition_id"]),
            int(selection["instrument_id"]),
            selection["execution_timeframe"],
            canonical_request_hash("parameters", selection["parameter_overrides"]),
        )
        instance = cache.get(identity)
        if not instance:
            candidates = StrategyInstance.objects.filter(
                portfolio=run.plan.portfolio,
                definition_id=identity[0],
                instrument_id=identity[1],
                timeframe=identity[2],
                execution_mode="SHADOW",
                enabled=False,
            )
            instance = next(
                (item for item in candidates if item.parameters == selection["parameter_overrides"]),
                None,
            )
        if not instance:
            definition = StrategyDefinition.objects.get(pk=identity[0], enabled=True)
            name = _instance_name(run, selection)
            suffix = 1
            while StrategyInstance.objects.filter(portfolio=run.plan.portfolio, name=name).exists():
                suffix += 1
                name = _instance_name(run, selection, suffix)
            instance, _ = create_instance(
                name=name,
                definition_key=definition.key,
                portfolio=run.plan.portfolio,
                instrument_id=identity[1],
                timeframe=identity[2],
                parameters=selection["parameter_overrides"],
                target_configuration={},
                execution_mode="SHADOW",
                qualify=False,
            )
        if instance.execution_mode != "SHADOW" or instance.enabled:
            raise ConstructionError("Construction-created strategy instances must remain disabled in SHADOW mode")
        cache[identity] = instance
        linked.append({"selection_id": selection["id"], "strategy_instance_id": instance.pk})
        GoalStrategySelection.objects.filter(pk=selection["id"]).update(created_strategy_instance=instance)
    return linked


@transaction.atomic
def apply_construction_run(construction_run, idempotency_key, *, mode="SHADOW"):
    run_id = construction_run.pk if isinstance(construction_run, PortfolioConstructionRun) else construction_run
    run = (
        PortfolioConstructionRun.objects.select_for_update(of=("self",))
        .select_related("plan__portfolio__account", "applied_rebalance")
        .get(pk=run_id)
    )
    if run.status != "COMPLETED":
        raise ConstructionError("Only a completed construction run can be applied")
    if any(item.get("apply_blocked") for item in run.goal_results):
        raise ConstructionError("Every non-cash-only goal must include at least one selected stock")
    if run.applied_rebalance_id:
        if run.application_idempotency_key == idempotency_key:
            return run, run.applied_rebalance, False
        raise ConstructionAlreadyApplied(run)
    run.application_status = "APPLYING"
    run.application_idempotency_key = idempotency_key
    run.save(update_fields=["application_status", "application_idempotency_key"])
    linked_instances = create_or_reuse_strategy_instances(run)
    rebalance = plan_construction_rebalance(
        run,
        f"{idempotency_key}:rebalance",
        mode=mode,
        strict_market_state=mode == "PAPER",
    )
    if rebalance.construction_run_id != run.pk:
        raise ConstructionError("Idempotency-Key was already used for a different construction application")
    run.applied_rebalance = rebalance
    run.applied_at = timezone.now()
    run.application_status = "APPLIED"
    run.metrics = {**run.metrics, "strategy_instances": linked_instances}
    run.save(update_fields=["applied_rebalance", "applied_at", "application_status", "metrics"])
    AuditEvent.objects.create(
        event_type="portfolio.construction.applied",
        actor="system",
        aggregate_type="portfolio",
        aggregate_id=str(run.plan.portfolio_id),
        data={
            "construction_run_id": run.pk,
            "rebalance_run_id": rebalance.pk,
            "strategy_instances": linked_instances,
            "mode": mode,
        },
        idempotency_key=f"audit:construction-apply:{idempotency_key}",
    )
    return run, rebalance, True
