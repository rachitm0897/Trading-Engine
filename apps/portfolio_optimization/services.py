from datetime import timedelta
from decimal import Decimal

import numpy as np
from django.db import transaction
from django.utils import timezone
from scipy.optimize import minimize

from apps.audit.models import AuditEvent, OutboxEvent
from apps.market_data.models import InstrumentPriceHistory
from apps.market_data.services import fetch_daily_history
from apps.portfolios.models import PortfolioPosition
from apps.strategies.models import StrategyAllocation

from .models import (
    OptimizedPortfolioTarget,
    PortfolioOptimizationPolicy,
    PortfolioOptimizationRun,
    PortfolioUniverse,
)


D = Decimal
TRADING_DAYS = 252


class OptimizationError(ValueError):
    pass


def _json_matrix(matrix):
    return [[str(float(value)) for value in row] for row in matrix]


def _feasible_start(current, lower, upper, total):
    weights = np.clip(np.asarray(current, dtype=float), lower, upper)
    for _ in range(100):
        difference = total - float(weights.sum())
        if abs(difference) <= 1e-10:
            break
        available = np.where(weights < upper - 1e-12)[0] if difference > 0 else np.where(weights > lower + 1e-12)[0]
        if not len(available):
            break
        step = difference / len(available)
        weights[available] = np.clip(weights[available] + step, lower, upper)
    if abs(float(weights.sum()) - total) > 1e-7:
        raise OptimizationError("Weight bounds cannot satisfy the target cash weight")
    return weights


def solve_markowitz(*, expected_returns, covariance, current_weights, method, cash_weight,
                    current_cash_weight=0, minimum_weight=0, maximum_weight=1,
                    maximum_turnover=1, transaction_cost_penalty=0, risk_free_rate=0,
                    long_only=True, external_current_weight=0):
    expected_returns = np.asarray(expected_returns, dtype=float)
    covariance = np.asarray(covariance, dtype=float)
    current = np.asarray(current_weights, dtype=float)
    count = len(expected_returns)
    if count < 2:
        raise OptimizationError("At least two instruments with sufficient history are required")
    if covariance.shape != (count, count) or current.shape != (count,):
        raise OptimizationError("Optimization inputs have inconsistent dimensions")
    cash_weight = float(cash_weight)
    stock_total = 1.0 - cash_weight
    lower = max(float(minimum_weight), 0.0) if long_only else float(minimum_weight)
    upper = float(maximum_weight)
    if not 0 <= cash_weight < 1:
        raise OptimizationError("Target cash weight must be between zero and one")
    if upper <= 0 or lower > upper:
        raise OptimizationError("Minimum and maximum weights are invalid")
    if count * lower > stock_total + 1e-10 or count * upper < stock_total - 1e-10:
        raise OptimizationError("Weight bounds are infeasible for the selected universe and cash target")
    if not np.all(np.isfinite(expected_returns)) or not np.all(np.isfinite(covariance)):
        raise OptimizationError("Expected returns and covariance must be finite")
    covariance = (covariance + covariance.T) / 2
    eigen_min = float(np.linalg.eigvalsh(covariance).min())
    if eigen_min < 1e-8:
        covariance = covariance + np.eye(count) * (1e-8 - eigen_min)
    start = _feasible_start(current, lower, upper, stock_total)
    max_turnover = float(maximum_turnover)
    # Match the rebalance planner's gross traded-notional convention: stock
    # weight changes count once; cash is the residual funding leg.
    fixed_turnover = abs(float(external_current_weight))

    def turnover(weights):
        return float(np.abs(weights - current).sum()) + fixed_turnover

    minimum_reachable = turnover(start)
    if max_turnover + 1e-8 < minimum_reachable:
        # Find the nearest feasible allocation before declaring the policy infeasible.
        nearest = minimize(
            lambda weights: float(np.abs(weights - current).sum()),
            start,
            method="SLSQP",
            bounds=[(lower, upper)] * count,
            constraints=[{"type": "eq", "fun": lambda weights: float(weights.sum()) - stock_total}],
            options={"maxiter": 500, "ftol": 1e-12},
        )
        minimum_reachable = turnover(nearest.x if nearest.success else start)
        if max_turnover + 1e-7 < minimum_reachable:
            raise OptimizationError(f"Maximum turnover is infeasible; at least {minimum_reachable:.6f} is required")
        start = nearest.x

    penalty = float(transaction_cost_penalty)
    risk_free = float(risk_free_rate)

    def portfolio_variance(weights):
        return max(float(weights @ covariance @ weights), 1e-16)

    if method == "MINIMUM_VARIANCE":
        objective = lambda weights: portfolio_variance(weights) + penalty * float(np.abs(weights - current).sum())
    elif method == "MAXIMUM_SHARPE":
        objective = lambda weights: -((float(expected_returns @ weights) - risk_free) / np.sqrt(portfolio_variance(weights))) + penalty * float(np.abs(weights - current).sum())
    else:
        raise OptimizationError("Unsupported optimization method")

    constraints = [{"type": "eq", "fun": lambda weights: float(weights.sum()) - stock_total}]
    if max_turnover < 10:
        constraints.append({"type": "ineq", "fun": lambda weights: max_turnover - turnover(weights)})
    result = minimize(
        objective,
        start,
        method="SLSQP",
        bounds=[(lower, upper)] * count,
        constraints=constraints,
        options={"maxiter": 1000, "ftol": 1e-12},
    )
    if not result.success:
        raise OptimizationError(f"Optimizer failed: {result.message}")
    weights = np.asarray(result.x, dtype=float)
    weights[np.abs(weights) < 1e-12] = 0
    if abs(float(weights.sum()) - stock_total) > 1e-6 or turnover(weights) > max_turnover + 1e-6:
        raise OptimizationError("Optimizer returned weights that violate configured constraints")
    variance = portfolio_variance(weights)
    expected_return = float(expected_returns @ weights)
    volatility = float(np.sqrt(variance))
    sharpe = (expected_return - risk_free) / volatility if volatility else 0.0
    marginal = covariance @ weights
    risk_contributions = weights * marginal / volatility if volatility else np.zeros(count)
    return {
        "weights": weights,
        "covariance": covariance,
        "objective_value": float(result.fun),
        "expected_return": expected_return,
        "expected_volatility": volatility,
        "sharpe_ratio": sharpe,
        "turnover": turnover(weights),
        "risk_contributions": risk_contributions,
        "solver_status": str(result.message),
    }


def universe_instruments(universe):
    instrument_map = {
        item.instrument_id: item.instrument
        for item in universe.memberships.filter(enabled=True, instrument__active=True, instrument__tradable=True, instrument__asset_class="STK").select_related("instrument")
    }
    if universe.include_strategy_instruments:
        allocations = StrategyAllocation.objects.filter(
            portfolio=universe.portfolio, strategy__enabled=True, strategy__kill_switch=False
        ).select_related("strategy__strategy_instance__instrument")
        for allocation in allocations:
            instance = getattr(allocation.strategy, "strategy_instance", None)
            if instance and instance.instrument.active and instance.instrument.tradable and instance.instrument.asset_class == "STK":
                instrument_map[instance.instrument_id] = instance.instrument
    return [instrument_map[key] for key in sorted(instrument_map)[:universe.maximum_instruments]]


def _load_prices(instruments, policy, minimum_observations, refresh_history):
    end_date = timezone.now().date()
    calendar_days = max(policy.lookback_days * 2, minimum_observations * 2)
    start_date = end_date - timedelta(days=calendar_days)
    warnings = []
    if refresh_history:
        for instrument in instruments:
            rows = InstrumentPriceHistory.objects.filter(
                instrument=instrument, provider="FINNHUB", trading_date__gte=start_date
            )
            latest = rows.order_by("-trading_date").first()
            if rows.count() < minimum_observations + 1 or not latest or latest.trading_date < end_date - timedelta(days=5):
                fetch_daily_history(instrument, start_date, end_date, purpose="OPTIMIZATION")
    series = {}
    excluded = []
    for instrument in instruments:
        prices = list(
            InstrumentPriceHistory.objects.filter(instrument=instrument, provider="FINNHUB")
            .order_by("-trading_date")[: policy.lookback_days + 1]
            .values_list("trading_date", "adjusted_close", "close")
        )
        mapping = {date: float(adjusted if adjusted is not None else close) for date, adjusted, close in prices if (adjusted or close) and float(adjusted if adjusted is not None else close) > 0}
        if len(mapping) < minimum_observations + 1:
            excluded.append({"instrument_id": instrument.pk, "symbol": instrument.symbol, "reason": "INSUFFICIENT_HISTORY", "observations": len(mapping)})
        else:
            series[instrument.pk] = mapping
    if excluded:
        warnings.append({"code": "INSTRUMENTS_EXCLUDED", "instruments": excluded})
    if len(series) < 2:
        raise OptimizationError("At least two universe instruments need sufficient aligned price history")
    common_dates = sorted(set.intersection(*(set(values) for values in series.values())))
    if len(common_dates) < minimum_observations + 1:
        raise OptimizationError(f"Only {max(len(common_dates) - 1, 0)} aligned returns are available; {minimum_observations} are required")
    common_dates = common_dates[-(policy.lookback_days + 1):]
    instrument_ids = sorted(series)
    matrix = np.asarray([[series[instrument_id][date] for instrument_id in instrument_ids] for date in common_dates], dtype=float)
    returns = matrix[1:] / matrix[:-1] - 1.0
    if not np.all(np.isfinite(returns)):
        raise OptimizationError("Historical price returns contain invalid values")
    return instrument_ids, common_dates, matrix, returns, warnings


def _current_weights(portfolio, nav, instrument_ids, available_cash=None):
    positions = PortfolioPosition.objects.filter(portfolio=portfolio).select_related("instrument")
    result = {}
    outside = D(0)
    for position in positions:
        value = D(position.quantity) * D(position.market_price)
        weight = value / nav if nav else D(0)
        if position.instrument_id in instrument_ids:
            result[position.instrument_id] = weight
        else:
            outside += abs(weight)
    cash = D(str(available_cash if available_cash is not None else portfolio.account.available_cash)) / nav
    return result, cash, outside


def _policy_snapshot(policy):
    return {
        "version": policy.version,
        "method": policy.method,
        "lookback_days": policy.lookback_days,
        "return_estimation": policy.return_estimation,
        "covariance_estimation": policy.covariance_estimation,
        "risk_free_rate": str(policy.risk_free_rate),
        "target_cash_weight": str(policy.target_cash_weight),
        "minimum_weight": str(policy.minimum_weight),
        "maximum_weight": str(policy.maximum_weight),
        "maximum_turnover": str(policy.maximum_turnover),
        "transaction_cost_penalty": str(policy.transaction_cost_penalty),
        "long_only": policy.long_only,
        "execution_mode": policy.execution_mode,
    }


def run_optimization(portfolio, idempotency_key, *, trigger="MANUAL", nav=None, available_cash=None,
                     refresh_history=True, flow_reference=""):
    existing = PortfolioOptimizationRun.objects.filter(idempotency_key=idempotency_key).first()
    if existing:
        return existing
    policy = PortfolioOptimizationPolicy.objects.filter(portfolio=portfolio, enabled=True).first()
    universe = PortfolioUniverse.objects.filter(portfolio=portfolio, enabled=True).first()
    if not policy or not universe:
        raise OptimizationError("An enabled portfolio universe and optimization policy are required")
    if policy.execution_mode not in {"SHADOW", "PAPER"}:
        raise OptimizationError("Optimization execution mode must be SHADOW or PAPER")
    nav = D(str(nav if nav is not None else portfolio.account.net_liquidation))
    if nav <= 0:
        raise OptimizationError("Portfolio NAV must be positive")
    run = PortfolioOptimizationRun.objects.create(
        portfolio=portfolio,
        policy=policy,
        universe=universe,
        idempotency_key=idempotency_key,
        trigger=trigger,
        nav=nav,
        cash_weight=policy.target_cash_weight,
        policy_snapshot=_policy_snapshot(policy),
        flow_reference=flow_reference,
    )
    try:
        instruments = universe_instruments(universe)
        if len(instruments) < 2:
            raise OptimizationError("Select at least two active stock instruments in the portfolio universe")
        instrument_ids, dates, prices, returns, warnings = _load_prices(
            instruments, policy, universe.minimum_history_observations, refresh_history
        )
        expected_returns = returns.mean(axis=0) * TRADING_DAYS
        covariance = np.cov(returns, rowvar=False, ddof=1) * TRADING_DAYS
        current, current_cash, outside = _current_weights(portfolio, nav, instrument_ids, available_cash)
        current_vector = np.asarray([float(current.get(instrument_id, 0)) for instrument_id in instrument_ids])
        solved = solve_markowitz(
            expected_returns=expected_returns,
            covariance=covariance,
            current_weights=current_vector,
            method=policy.method,
            cash_weight=policy.target_cash_weight,
            current_cash_weight=current_cash,
            minimum_weight=policy.minimum_weight,
            maximum_weight=policy.maximum_weight,
            maximum_turnover=policy.maximum_turnover,
            transaction_cost_penalty=policy.transaction_cost_penalty,
            risk_free_rate=policy.risk_free_rate,
            long_only=policy.long_only,
            external_current_weight=outside,
        )
        instrument_map = {instrument.pk: instrument for instrument in instruments}
        with transaction.atomic():
            for rank, (instrument_id, weight) in enumerate(sorted(zip(instrument_ids, solved["weights"]), key=lambda item: -item[1])):
                index = instrument_ids.index(instrument_id)
                current_weight = current.get(instrument_id, D(0))
                constraint = ""
                if abs(float(weight) - float(policy.minimum_weight)) < 1e-6:
                    constraint = "MINIMUM_WEIGHT"
                elif abs(float(weight) - float(policy.maximum_weight)) < 1e-6:
                    constraint = "MAXIMUM_WEIGHT"
                OptimizedPortfolioTarget.objects.create(
                    optimization_run=run,
                    instrument=instrument_map[instrument_id],
                    current_weight=D(str(float(current_weight))),
                    optimized_weight=D(str(float(weight))),
                    weight_change=D(str(float(weight) - float(current_weight))),
                    target_value=D(str(float(weight))) * nav,
                    expected_return_contribution=D(str(float(weight * expected_returns[index]))),
                    risk_contribution=D(str(float(solved["risk_contributions"][index]))),
                    constraint_status=constraint,
                    rank=rank,
                )
            run.input_start_date = dates[0]
            run.input_end_date = dates[-1]
            run.current_weights = {str(key): str(value) for key, value in current.items()} | {"cash": str(current_cash), "outside_universe": str(outside)}
            run.expected_returns = {str(instrument_id): str(float(expected_returns[index])) for index, instrument_id in enumerate(instrument_ids)}
            run.covariance_snapshot = {"instrument_ids": instrument_ids, "matrix": _json_matrix(solved["covariance"]), "observations": len(returns)}
            run.constraints_snapshot = {
                "stock_weight_total": str(D(1) - D(policy.target_cash_weight)),
                "minimum_weight": str(policy.minimum_weight),
                "maximum_weight": str(policy.maximum_weight),
                "maximum_turnover": str(policy.maximum_turnover),
                "long_only": policy.long_only,
            }
            run.solver_status = solved["solver_status"]
            run.objective_value = D(str(solved["objective_value"]))
            run.expected_return = D(str(solved["expected_return"]))
            run.expected_volatility = D(str(solved["expected_volatility"]))
            run.sharpe_ratio = D(str(solved["sharpe_ratio"]))
            run.turnover = D(str(solved["turnover"]))
            run.warnings = warnings
            run.status = "COMPLETED"
            run.completed_at = timezone.now()
            run.save()
            OutboxEvent.objects.create(
                topic="portfolio.optimization.completed.v1",
                event_type="portfolio.optimization.completed",
                aggregate_type="portfolio",
                aggregate_id=str(portfolio.pk),
                partition_key=str(portfolio.pk),
                payload={"optimization_run_id": run.pk, "method": policy.method, "turnover": str(run.turnover)},
                idempotency_key=f"optimization:{run.pk}:completed",
            )
            AuditEvent.objects.create(
                event_type="portfolio.optimization.completed",
                actor="system",
                aggregate_type="portfolio",
                aggregate_id=str(portfolio.pk),
                data={"optimization_run_id": run.pk, "trigger": trigger, "policy_version": policy.version},
                idempotency_key=f"audit:optimization:{run.pk}:completed",
            )
        return run
    except Exception as exc:
        run.status = "FAILED"
        run.solver_status = "FAILED"
        run.error_details = {"message": str(exc), "type": exc.__class__.__name__}
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "solver_status", "error_details", "completed_at"])
        if isinstance(exc, OptimizationError):
            raise
        raise OptimizationError(str(exc)) from exc


def latest_prices(optimization_run):
    result = {}
    for target in optimization_run.targets.select_related("instrument"):
        price = InstrumentPriceHistory.objects.filter(
            instrument=target.instrument, provider="FINNHUB"
        ).order_by("-trading_date").first()
        if not price:
            raise OptimizationError(f"No historical reference price is available for {target.instrument.symbol}")
        result[target.instrument_id] = price.adjusted_close or price.close
    for position in PortfolioPosition.objects.filter(portfolio=optimization_run.portfolio):
        if position.instrument_id not in result and position.market_price > 0:
            result[position.instrument_id] = position.market_price
    return result


def plan_optimized_rebalance(optimization_run, idempotency_key, *, mode="SHADOW", strict_market_state=False,
                             available_cash=None, prices=None):
    if optimization_run.status != "COMPLETED":
        raise OptimizationError("Only a completed optimization run can create rebalance targets")
    from apps.rebalancing.services import plan_rebalance

    return plan_rebalance(
        optimization_run.portfolio,
        optimization_run.trigger,
        idempotency_key,
        prices=prices or latest_prices(optimization_run),
        nav=optimization_run.nav,
        available_cash=available_cash,
        mode=mode,
        strict_market_state=strict_market_state,
        optimization_run=optimization_run,
    )
