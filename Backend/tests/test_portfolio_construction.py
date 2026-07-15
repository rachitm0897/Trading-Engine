from datetime import timedelta
from decimal import Decimal
import json

import pytest
from django.utils import timezone

from apps.accounts.models import BrokerAccount
from apps.allocation.models import RebalancePolicy
from apps.audit.models import AuditEvent, OperationAttempt
from apps.instruments.models import BrokerContract, Instrument
from apps.market_data.models import InstrumentPriceHistory
from apps.portfolio_construction.models import (
    GoalStrategySelection,
    PortfolioConstructionPlan,
    PortfolioConstructionRun,
    PortfolioGoalAllocation,
    StrategyConstructionProfile,
)
from apps.portfolio_construction.rules import MAXIMUM_RISK, resolved_goal_rules, validate_timeframe_risk
from apps.portfolio_construction.services import (
    ConstructionAlreadyApplied,
    ConstructionError,
    apply_construction_run,
    create_construction_run,
    eligible_strategies,
    plan_construction_rebalance,
    plan_validation,
    run_construction,
)
from apps.portfolios.models import TradingPortfolio
from apps.strategies.models import StrategyDefinition, StrategyInstance


pytestmark = pytest.mark.django_db
D = Decimal


def construction_case(symbols=("AAA", "BBB", "CCC")):
    suffix = BrokerAccount.objects.count() + 1
    account = BrokerAccount.objects.create(
        account_id=f"DU-BUILDER-{suffix}", net_liquidation=10000, available_cash=10000
    )
    portfolio = TradingPortfolio.objects.create(name="Builder portfolio", account=account)
    instruments = []
    start = timezone.now().date() - timedelta(days=79)
    for index, symbol in enumerate(symbols, start=1):
        instrument = Instrument.objects.create(symbol=symbol)
        BrokerContract.objects.create(instrument=instrument, conid=8000 + index)
        instruments.append(instrument)
        for offset in range(80):
            drift = D("0.0007") + D(index) * D("0.00015")
            cycle = D((offset % (4 + index)) - 2) * D("0.0002")
            price = D("100") * (D(1) + drift) ** offset * (D(1) + cycle)
            InstrumentPriceHistory.objects.create(
                instrument=instrument,
                trading_date=start + timedelta(days=offset),
                open=price,
                high=price,
                low=price,
                close=price,
                adjusted_close=price,
                volume=100000,
                fetched_at=timezone.now(),
            )
    RebalancePolicy.objects.create(
        portfolio=portfolio,
        maximum_turnover="2",
        minimum_trade_notional="1",
        fee_buffer="0",
        cash_buffer_percent="0",
    )
    return portfolio, instruments


def add_goal(plan, name, weight, timeframe, risk, order=0):
    return PortfolioGoalAllocation.objects.create(
        plan=plan,
        name=name,
        allocation_weight=weight,
        timeframe_bucket=timeframe,
        risk_level=risk,
        display_order=order,
    )


def add_selection(goal, instrument, definition=None):
    definition = definition or StrategyDefinition.objects.get(key="FIXED_WEIGHT_REBALANCE")
    return GoalStrategySelection.objects.create(
        goal_allocation=goal,
        strategy_definition=definition,
        instrument=instrument,
        execution_timeframe="1d",
        parameter_overrides={"direction": "LONG"},
    )


@pytest.mark.parametrize("timeframe", ["NOW", "HURRY", "FAST", "BUILD", "GROW", "COMPOUND"])
def test_all_timeframe_rules_are_fixed_and_valid(timeframe):
    rules = resolved_goal_rules(timeframe, MAXIMUM_RISK[timeframe])
    assert rules["timeframe_bucket"] == timeframe
    assert rules["lookback_days"] == 252
    assert rules["minimum_history_observations"] == 60
    assert rules["long_only"] is True


@pytest.mark.parametrize("risk", [1, 2, 3, 4, 5])
def test_all_risk_rules_have_fixed_caps_and_optimizer_methods(risk):
    rules = resolved_goal_rules("GROW", risk)
    assert rules["risk_level"] == risk
    assert rules["maximum_stock_weight"] > 0
    assert rules["optimizer_method"] == ("MINIMUM_VARIANCE" if risk <= 3 else "MAXIMUM_SHARPE")


@pytest.mark.parametrize("timeframe,risk", [("NOW", 2), ("HURRY", 3), ("FAST", 4), ("BUILD", 5)])
def test_invalid_timeframe_risk_combinations_are_rejected(timeframe, risk):
    with pytest.raises(ValueError, match="exceeds the maximum"):
        validate_timeframe_risk(timeframe, risk)


def test_drafts_allow_incomplete_or_excess_allocations_but_preview_requires_exact_total():
    portfolio, _ = construction_case(())
    plan = PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    add_goal(plan, "Incomplete", "0.40", "BUILD", 3)
    assert plan_validation(plan)["ready_to_preview"] is False
    add_goal(plan, "Excess", "0.70", "GROW", 4)
    validation = plan_validation(plan)
    assert validation["allocated_weight"] == D("1.10")
    assert validation["validation_errors"][0]["code"] == "ALLOCATION_TOTAL"
    with pytest.raises(ConstructionError, match="exactly 100%"):
        create_construction_run(plan, "not-ready", refresh_history=False)


def test_plan_goal_api_exposes_totals_rules_and_audits_mutations(client):
    portfolio, _ = construction_case(())
    created = client.post(
        "/api/v1/portfolio-construction/plans/",
        json.dumps({"portfolio_id": portfolio.pk, "name": "Goals"}),
        content_type="application/json",
    )
    assert created.status_code == 201
    plan = created.json()["data"]
    goal = client.post(
        f"/api/v1/portfolio-construction/plans/{plan['id']}/goals/",
        json.dumps({
            "name": "Growth",
            "allocation_percentage": "50",
            "timeframe_bucket": "GROW",
            "risk_level": 4,
        }),
        content_type="application/json",
    )
    assert goal.status_code == 201
    detail = client.get(f"/api/v1/portfolio-construction/plans/{plan['id']}/").json()["data"]
    assert D(detail["allocated_percentage"]) == D(50)
    assert detail["ready_to_preview"] is False
    assert detail["goals"][0]["resolved_rules"]["optimizer_method"] == "MAXIMUM_SHARPE"
    changed = client.patch(
        f"/api/v1/portfolio-construction/goals/{goal.json()['data']['id']}/",
        json.dumps({"allocation_percentage": "100"}),
        content_type="application/json",
    )
    assert changed.status_code == 200
    assert client.get(f"/api/v1/portfolio-construction/plans/{plan['id']}/").json()["data"]["ready_to_preview"] is True
    assert AuditEvent.objects.filter(event_type="portfolio.construction_goal.created").exists()
    assert AuditEvent.objects.filter(event_type="portfolio.construction_goal.changed").exists()


def test_strategy_eligibility_returns_eligible_and_rejected_reasons(client):
    portfolio, instruments = construction_case(("AAA",))
    plan = PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    goal = add_goal(plan, "Conservative", "1", "HURRY", 1)
    result = eligible_strategies(goal)
    assert any(item["key"] == "FIXED_WEIGHT_REBALANCE" for item in result["eligible"])
    assert result["rejected"]
    assert all(item["reason"] for item in result["rejected"])
    post = client.post(
        f"/api/v1/portfolio-construction/goals/{goal.pk}/selections/",
        json.dumps({
            "strategy_key": "FIXED_WEIGHT_REBALANCE",
            "instrument_id": instruments[0].pk,
            "execution_timeframe": "1d",
            "parameter_overrides": {"direction": "LONG"},
        }),
        content_type="application/json",
    )
    assert post.status_code == 201
    assert post.json()["data"]["symbol"] == "AAA"
    assert StrategyConstructionProfile.objects.count() == 5


def test_cash_only_and_one_stock_goal_edges_are_explainable():
    portfolio, _ = construction_case(())
    cash_plan = PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    cash_goal = add_goal(cash_plan, "Immediate", "1", "NOW", 1)
    cash = run_construction(create_construction_run(cash_plan, "cash-only", refresh_history=False), refresh_history=False)
    assert cash.final_target_weights == {"cash": "1", "stocks": {}}
    assert cash.goal_results[0]["intentionally_cash_only"] is True

    stock_portfolio, instruments = construction_case(("AAA",))
    stock_plan = PortfolioConstructionPlan.objects.create(portfolio=stock_portfolio)
    stock_goal = add_goal(stock_plan, "Aggressive", "1", "GROW", 5)
    add_selection(stock_goal, instruments[0])
    stock = run_construction(create_construction_run(stock_plan, "one-stock", refresh_history=False), refresh_history=False)
    assert stock.final_target_weights["stocks"][str(instruments[0].pk)] == "0.25000000"
    assert stock.final_target_weights["cash"] == "0.75000000"
    assert stock.goal_results[0]["warnings"][0]["code"] == "SINGLE_STOCK_LIMIT"


def test_no_stock_non_cash_goal_previews_cash_but_blocks_apply():
    portfolio, _ = construction_case(())
    plan = PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    add_goal(plan, "Missing choices", "1", "GROW", 5)
    run = run_construction(create_construction_run(plan, "empty-goal", refresh_history=False), refresh_history=False)
    assert run.status == "COMPLETED"
    assert run.goal_results[0]["apply_blocked"] is True
    with pytest.raises(ConstructionError, match="must include at least one"):
        apply_construction_run(run, "empty-apply")


def test_two_goal_preview_merges_duplicate_stocks_and_preserves_existing_optimizer_records():
    portfolio, instruments = construction_case()
    plan = PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    first = add_goal(plan, "Growth", "0.50", "GROW", 4, 1)
    second = add_goal(plan, "Aggressive", "0.50", "GROW", 5, 2)
    for instrument in instruments[:2]:
        add_selection(first, instrument)
    for instrument in (instruments[0], instruments[2]):
        add_selection(second, instrument)
    run = run_construction(create_construction_run(plan, "fifty-fifty", refresh_history=False), refresh_history=False)
    weights = run.final_target_weights
    assert run.status == "COMPLETED"
    assert set(weights["stocks"]) == {str(item.pk) for item in instruments}
    assert weights["stocks"][str(instruments[0].pk)] == "0.22500000"
    assert sum(D(value) for value in weights["stocks"].values()) + D(weights["cash"]) == D(1)
    shared = run.targets.get(instrument=instruments[0])
    assert len(shared.goal_contributions) == 2
    assert run.metrics["expected_volatility"] is not None
    assert not hasattr(portfolio, "optimization_universe")


def test_async_preview_retry_records_attempts_and_is_idempotent(client, monkeypatch):
    portfolio, instruments = construction_case(("AAA", "BBB"))
    plan = PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    goal = add_goal(plan, "Retry", "1", "GROW", 5)
    for instrument in instruments:
        add_selection(goal, instrument)
    payload = json.dumps({"plan_id": plan.pk, "refresh_history": False})
    queued = client.post(
        "/api/v1/portfolio-construction/preview/",
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="builder-retry",
    )
    assert queued.status_code == 202
    run_id = queued.json()["data"]["id"]
    from apps.portfolio_construction import services
    from apps.portfolio_construction.tasks import execute_construction_run

    real = services.optimize_explicit_universe
    calls = {"count": 0}

    def flaky(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary construction worker failure")
        return real(*args, **kwargs)

    monkeypatch.setattr(services, "optimize_explicit_universe", flaky)
    with pytest.raises(ConstructionError, match="temporary construction worker failure"):
        execute_construction_run.run(run_id, False, False)
    failed = PortfolioConstructionRun.objects.get(pk=run_id)
    assert failed.status == "FAILED" and failed.retryable is True
    retried = client.post(
        "/api/v1/portfolio-construction/preview/",
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="builder-retry",
        HTTP_IDEMPOTENCY_RETRY="true",
    )
    assert retried.status_code == 202
    execute_construction_run.run(run_id, False, False)
    assert PortfolioConstructionRun.objects.get(pk=run_id).status == "COMPLETED"
    assert list(OperationAttempt.objects.filter(
        operation_type="PORTFOLIO_CONSTRUCTION", operation_id=str(run_id)
    ).values_list("status", flat=True)) == ["FAILED", "COMPLETED"]


def test_apply_creates_one_net_construction_rebalance_and_reuses_disabled_shadow_instances():
    portfolio, instruments = construction_case()
    plan = PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    first = add_goal(plan, "Growth", "0.50", "GROW", 4, 1)
    second = add_goal(plan, "Aggressive", "0.50", "GROW", 5, 2)
    first_a = add_selection(first, instruments[0])
    add_selection(first, instruments[1])
    second_a = add_selection(second, instruments[0])
    add_selection(second, instruments[2])
    run = run_construction(create_construction_run(plan, "apply-preview", refresh_history=False), refresh_history=False)
    preview = plan_construction_rebalance(run, "apply-preview:rebalance", mode="SHADOW")
    assert preview.target_source == "GOAL_CONSTRUCTION"
    applied, rebalance, created = apply_construction_run(run, "apply-once", mode="SHADOW")
    assert created is True
    assert rebalance.target_source == "GOAL_CONSTRUCTION"
    assert rebalance.construction_run_id == run.pk
    assert rebalance.targets.count() == 3
    assert applied.applied_rebalance_id == rebalance.pk
    assert StrategyInstance.objects.filter(portfolio=portfolio).count() == 3
    assert not StrategyInstance.objects.filter(portfolio=portfolio, enabled=True).exists()
    assert not StrategyInstance.objects.filter(portfolio=portfolio).exclude(execution_mode="SHADOW").exists()
    first_a.refresh_from_db()
    second_a.refresh_from_db()
    assert first_a.created_strategy_instance_id == second_a.created_strategy_instance_id
    same, same_rebalance, duplicate_created = apply_construction_run(run, "apply-once", mode="SHADOW")
    assert duplicate_created is False and same_rebalance.pk == rebalance.pk
    with pytest.raises(ConstructionAlreadyApplied):
        apply_construction_run(run, "apply-again", mode="SHADOW")


def test_apply_api_queues_polls_and_returns_identical_one_time_result(client):
    portfolio, instruments = construction_case(("AAA",))
    plan = PortfolioConstructionPlan.objects.create(portfolio=portfolio)
    goal = add_goal(plan, "API apply", "1", "GROW", 5)
    add_selection(goal, instruments[0])
    run = run_construction(
        create_construction_run(plan, "api-apply-preview", refresh_history=False),
        refresh_history=False,
    )
    payload = json.dumps({"plan_id": plan.pk, "portfolio_id": portfolio.pk})
    queued = client.post(
        f"/api/v1/portfolio-construction/runs/{run.pk}/apply/",
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="api-apply-once",
    )
    assert queued.status_code == 202
    assert queued.json()["data"]["application_status"] == "QUEUED"
    from apps.portfolio_construction.tasks import apply_construction_run_task

    apply_construction_run_task.run(run.pk, "api-apply-once", "SHADOW")
    polled = client.get(f"/api/v1/portfolio-construction/runs/{run.pk}/").json()["data"]
    assert polled["application_status"] == "APPLIED"
    assert polled["applied_rebalance"]["id"]
    assert polled["strategy_instances"][0]["strategy_instance_id"]
    same = client.post(
        f"/api/v1/portfolio-construction/runs/{run.pk}/apply/",
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="api-apply-once",
    )
    duplicate = client.post(
        f"/api/v1/portfolio-construction/runs/{run.pk}/apply/",
        payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="api-apply-again",
    )
    assert same.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "CONSTRUCTION_ALREADY_APPLIED"
