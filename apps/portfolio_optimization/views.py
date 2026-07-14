import json
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt

from apps.core.views import response
from apps.instruments.models import Instrument
from apps.portfolios.models import TradingPortfolio

from .models import (
    PortfolioOptimizationPolicy,
    PortfolioOptimizationRun,
    PortfolioUniverse,
    PortfolioUniverseInstrument,
)
from .services import OptimizationError, plan_optimized_rebalance, run_optimization


POLICY_FIELDS = [
    "name", "method", "lookback_days", "return_estimation", "covariance_estimation", "risk_free_rate",
    "target_cash_weight", "minimum_weight", "maximum_weight", "maximum_turnover",
    "transaction_cost_penalty", "long_only", "enabled",
]


def _universe_row(universe):
    memberships = universe.memberships.select_related("instrument").order_by("instrument__symbol")
    return {
        "id": universe.pk,
        "portfolio_id": universe.portfolio_id,
        "name": universe.name,
        "include_strategy_instruments": universe.include_strategy_instruments,
        "minimum_history_observations": universe.minimum_history_observations,
        "maximum_instruments": universe.maximum_instruments,
        "enabled": universe.enabled,
        "instruments": [
            {"instrument_id": item.instrument_id, "symbol": item.instrument.symbol, "enabled": item.enabled}
            for item in memberships
        ],
        "updated_at": universe.updated_at,
    }


def _policy_row(policy):
    return {"id": policy.pk, "portfolio_id": policy.portfolio_id, **{field: getattr(policy, field) for field in POLICY_FIELDS},
            "execution_mode": policy.execution_mode, "version": policy.version, "updated_at": policy.updated_at}


def _target_row(target):
    return {
        "id": target.pk,
        "instrument_id": target.instrument_id,
        "symbol": target.instrument.symbol,
        "current_weight": target.current_weight,
        "optimized_weight": target.optimized_weight,
        "weight_change": target.weight_change,
        "target_value": target.target_value,
        "expected_return_contribution": target.expected_return_contribution,
        "risk_contribution": target.risk_contribution,
        "constraint_status": target.constraint_status,
        "rank": target.rank,
    }


def _run_row(run, detail=False):
    row = {
        "id": run.pk,
        "portfolio_id": run.portfolio_id,
        "policy_id": run.policy_id,
        "universe_id": run.universe_id,
        "trigger": run.trigger,
        "status": run.status,
        "input_start_date": run.input_start_date,
        "input_end_date": run.input_end_date,
        "nav": run.nav,
        "objective_value": run.objective_value,
        "expected_return": run.expected_return,
        "expected_volatility": run.expected_volatility,
        "sharpe_ratio": run.sharpe_ratio,
        "turnover": run.turnover,
        "cash_weight": run.cash_weight,
        "solver_status": run.solver_status,
        "warnings": run.warnings,
        "error_details": run.error_details,
        "flow_reference": run.flow_reference,
        "created_at": run.created_at,
        "completed_at": run.completed_at,
    }
    if detail:
        row["policy_snapshot"] = run.policy_snapshot
        row["constraints"] = run.constraints_snapshot
        row["current_weights"] = run.current_weights
        row["targets"] = [_target_row(item) for item in run.targets.select_related("instrument").order_by("rank")]
        rebalance = run.rebalances.order_by("-created_at").first()
        row["rebalance"] = None
        row["planned_trades"] = []
        if rebalance:
            row["rebalance"] = {
                "id": rebalance.pk,
                "mode": rebalance.mode,
                "status": rebalance.status,
                "phase": rebalance.phase,
                "planned_turnover": rebalance.planned_turnover,
            }
            row["planned_trades"] = [
                {
                    "instrument_id": target.instrument_id,
                    "symbol": target.instrument.symbol,
                    "side": "BUY" if target.trade_quantity > 0 else "SELL" if target.trade_quantity < 0 else "NONE",
                    "quantity": abs(target.trade_quantity),
                    "reference_price": target.reference_price,
                    "estimated_cost": target.estimated_cost,
                    "suppressed": target.suppressed,
                    "suppression_reason": target.suppression_reason,
                }
                for target in rebalance.targets.select_related("instrument").order_by("rank")
            ]
    return row


@csrf_exempt
def universes(request):
    if request.method == "GET":
        query = PortfolioUniverse.objects.all().select_related("portfolio")
        if request.GET.get("portfolio"):
            query = query.filter(portfolio_id=request.GET["portfolio"])
        return response([_universe_row(item) for item in query])
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET or POST required", "details": {}})
    try:
        payload = json.loads(request.body or b"{}")
        portfolio = TradingPortfolio.objects.get(pk=payload["portfolio_id"])
        instrument_ids = list(dict.fromkeys(int(item) for item in payload.get("instrument_ids", [])))
        if len(instrument_ids) < 2:
            raise ValueError("Select at least two instruments")
        instruments = list(Instrument.objects.filter(pk__in=instrument_ids, active=True, tradable=True, asset_class="STK"))
        if len(instruments) != len(instrument_ids):
            raise ValueError("Universe instruments must be active, tradable stocks")
        with transaction.atomic():
            universe, _ = PortfolioUniverse.objects.update_or_create(
                portfolio=portfolio,
                defaults={
                    "name": str(payload.get("name") or "Default universe")[:128],
                    "include_strategy_instruments": bool(payload.get("include_strategy_instruments", False)),
                    "minimum_history_observations": int(payload.get("minimum_history_observations", 60)),
                    "maximum_instruments": int(payload.get("maximum_instruments", 50)),
                    "enabled": bool(payload.get("enabled", True)),
                },
            )
            if universe.minimum_history_observations < 20 or universe.maximum_instruments < 2:
                raise ValueError("Minimum history must be at least 20 observations and maximum instruments at least two")
            universe.memberships.exclude(instrument_id__in=instrument_ids).delete()
            for instrument in instruments:
                PortfolioUniverseInstrument.objects.update_or_create(
                    universe=universe, instrument=instrument, defaults={"enabled": True}
                )
        return response(_universe_row(universe), status=201)
    except (KeyError, ValueError, TypeError, json.JSONDecodeError, TradingPortfolio.DoesNotExist) as exc:
        return response(status=400, error={"code": "INVALID_PORTFOLIO_UNIVERSE", "message": str(exc), "details": {}})


@csrf_exempt
def policies(request):
    if request.method == "GET":
        query = PortfolioOptimizationPolicy.objects.all().select_related("portfolio")
        if request.GET.get("portfolio"):
            query = query.filter(portfolio_id=request.GET["portfolio"])
        return response([_policy_row(item) for item in query])
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "GET or POST required", "details": {}})
    try:
        payload = json.loads(request.body or b"{}")
        portfolio = TradingPortfolio.objects.get(pk=payload["portfolio_id"])
        values = {field: payload[field] for field in POLICY_FIELDS if field in payload}
        values["execution_mode"] = "SHADOW"
        if values.get("method", "MINIMUM_VARIANCE") not in {value for value, _ in PortfolioOptimizationPolicy.METHODS}:
            raise ValueError("Method must be MINIMUM_VARIANCE or MAXIMUM_SHARPE")
        policy = PortfolioOptimizationPolicy.objects.filter(portfolio=portfolio).first()
        minimum = Decimal(str(values.get("minimum_weight", policy.minimum_weight if policy else "0")))
        maximum = Decimal(str(values.get("maximum_weight", policy.maximum_weight if policy else "1")))
        cash = Decimal(str(values.get("target_cash_weight", policy.target_cash_weight if policy else "0.02")))
        turnover = Decimal(str(values.get("maximum_turnover", policy.maximum_turnover if policy else "1")))
        transaction_penalty = Decimal(str(values.get("transaction_cost_penalty", policy.transaction_cost_penalty if policy else "0")))
        lookback_days = int(values.get("lookback_days", policy.lookback_days if policy else 252))
        long_only = bool(values.get("long_only", policy.long_only if policy else True))
        if minimum < 0 or maximum <= 0 or minimum > maximum:
            raise ValueError("Long-only minimum and maximum weights are invalid")
        if cash < 0 or cash >= 1:
            raise ValueError("Target cash weight must be at least zero and less than one")
        if turnover < 0:
            raise ValueError("Maximum turnover cannot be negative")
        if transaction_penalty < 0:
            raise ValueError("Transaction-cost penalty cannot be negative")
        if lookback_days < 30:
            raise ValueError("Lookback must be at least 30 days")
        if not long_only:
            raise ValueError("This release supports long-only optimization only")
        with transaction.atomic():
            if policy:
                for field, value in values.items():
                    setattr(policy, field, value)
                policy.version += 1
                policy.save()
            else:
                policy = PortfolioOptimizationPolicy.objects.create(portfolio=portfolio, **values)
        return response(_policy_row(policy), status=201)
    except (KeyError, ValueError, InvalidOperation, TypeError, json.JSONDecodeError, TradingPortfolio.DoesNotExist) as exc:
        return response(status=400, error={"code": "INVALID_OPTIMIZATION_POLICY", "message": str(exc), "details": {}})


@csrf_exempt
def execute(request, preview=False):
    if request.method != "POST":
        return response(status=405, error={"code": "METHOD_NOT_ALLOWED", "message": "POST required", "details": {}})
    key = request.headers.get("Idempotency-Key")
    if not key:
        return response(status=400, error={"code": "IDEMPOTENCY_KEY_REQUIRED", "message": "Idempotency-Key header is required", "details": {}})
    try:
        payload = json.loads(request.body or b"{}")
        if preview:
            portfolio = TradingPortfolio.objects.select_related("account").get(pk=payload["portfolio_id"])
            run = run_optimization(
                portfolio,
                key,
                trigger=str(payload.get("trigger") or "PREVIEW").upper(),
                nav=payload.get("nav"),
                refresh_history=bool(payload.get("refresh_history", True)),
            )
            if not run.rebalances.exists():
                plan_optimized_rebalance(run, f"{key}:rebalance", mode="SHADOW", strict_market_state=False)
        else:
            run = PortfolioOptimizationRun.objects.select_related("portfolio__account").get(pk=payload["optimization_run_id"])
            mode = "SHADOW" if settings.NEW_EXECUTION_MODE == "SHADOW" else "PAPER"
            plan_optimized_rebalance(run, f"{key}:rebalance", mode=mode, strict_market_state=mode == "PAPER")
        run.refresh_from_db()
        return response(_run_row(run, True), status=201)
    except (KeyError, ValueError, InvalidOperation, OptimizationError, json.JSONDecodeError,
            TradingPortfolio.DoesNotExist, PortfolioOptimizationRun.DoesNotExist) as exc:
        return response(status=400, error={"code": "OPTIMIZATION_FAILED", "message": str(exc), "details": {}})


def runs(request, run_id=None):
    if run_id:
        try:
            return response(_run_row(PortfolioOptimizationRun.objects.get(pk=run_id), True))
        except PortfolioOptimizationRun.DoesNotExist:
            return response(status=404, error={"code": "NOT_FOUND", "message": "Optimization run not found", "details": {}})
    query = PortfolioOptimizationRun.objects.all().order_by("-created_at")
    if request.GET.get("portfolio"):
        query = query.filter(portfolio_id=request.GET["portfolio"])
    return response([_run_row(item) for item in query[:100]])
