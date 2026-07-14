from datetime import date, timedelta
from decimal import Decimal
import json

import numpy as np
import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import BrokerAccount
from apps.allocation.models import AllocationDecision, RebalancePolicy, StrategyCapitalSnapshot
from apps.allocation.services import create_flow
from apps.instruments.models import BrokerContract, Instrument
from apps.market_data.models import InstrumentPriceHistory
from apps.oms.models import OrderIntent
from apps.portfolio_optimization.models import (
    PortfolioOptimizationPolicy,
    PortfolioOptimizationRun,
    PortfolioUniverse,
    PortfolioUniverseInstrument,
)
from apps.portfolio_optimization.services import (
    UniverseSizeError,
    plan_optimized_rebalance,
    run_optimization,
    solve_markowitz,
)
from apps.portfolios.models import TradingPortfolio
from apps.position_sizing.models import PositionSizingDecision
from apps.strategies.models import StrategyAllocation, TradingStrategy


pytestmark = pytest.mark.django_db


def test_markowitz_methods_enforce_cash_bounds_and_turnover():
    covariance = np.array([[0.04, 0.006, 0.004], [0.006, 0.09, 0.01], [0.004, 0.01, 0.16]])
    expected = np.array([0.07, 0.13, 0.18])
    current = np.array([0.50, 0.25, 0.15])
    for method in ["MINIMUM_VARIANCE", "MAXIMUM_SHARPE"]:
        result = solve_markowitz(
            expected_returns=expected,
            covariance=covariance,
            current_weights=current,
            method=method,
            cash_weight=0.10,
            minimum_weight=0.05,
            maximum_weight=0.70,
            maximum_turnover=0.40,
            transaction_cost_penalty=0.01,
            risk_free_rate=0.02,
            long_only=True,
        )
        assert result["weights"].sum() == pytest.approx(0.90, abs=1e-7)
        assert min(result["weights"]) >= 0.05 - 1e-7
        assert max(result["weights"]) <= 0.70 + 1e-7
        assert result["turnover"] <= 0.40 + 1e-7
        assert result["expected_volatility"] > 0


def test_transaction_cost_penalty_reduces_turnover():
    arguments = {
        "expected_returns": [0.04, 0.20],
        "covariance": [[0.03, 0.002], [0.002, 0.05]],
        "current_weights": [0.80, 0.20],
        "method": "MAXIMUM_SHARPE",
        "cash_weight": 0,
        "minimum_weight": 0,
        "maximum_weight": 1,
        "maximum_turnover": 2,
        "risk_free_rate": 0,
        "long_only": True,
    }
    unpenalized = solve_markowitz(**arguments, transaction_cost_penalty=0)
    penalized = solve_markowitz(**arguments, transaction_cost_penalty=10)
    assert penalized["turnover"] < unpenalized["turnover"]


def _optimization_case():
    account = BrokerAccount.objects.create(account_id="DU-OPT", net_liquidation=10000, available_cash=10000)
    portfolio = TradingPortfolio.objects.create(name="Optimized", account=account)
    instruments = [Instrument.objects.create(symbol=symbol) for symbol in ["AAA", "BBB"]]
    for index, instrument in enumerate(instruments, start=1):
        BrokerContract.objects.create(instrument=instrument, conid=1000 + index)
    universe = PortfolioUniverse.objects.create(portfolio=portfolio, minimum_history_observations=30)
    for instrument in instruments:
        PortfolioUniverseInstrument.objects.create(universe=universe, instrument=instrument)
    policy = PortfolioOptimizationPolicy.objects.create(
        portfolio=portfolio,
        method="MINIMUM_VARIANCE",
        lookback_days=60,
        target_cash_weight="0.10",
        maximum_weight="0.80",
        maximum_turnover="1.00",
    )
    start = timezone.now().date() - timedelta(days=69)
    for offset in range(70):
        for index, instrument in enumerate(instruments):
            price = Decimal("100") * (Decimal("1.001") + Decimal(index) * Decimal("0.0005")) ** offset
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
    return portfolio, instruments, policy


def test_optimization_targets_use_existing_rebalance_and_sizing_pipeline():
    portfolio, instruments, _ = _optimization_case()
    RebalancePolicy.objects.create(
        portfolio=portfolio,
        maximum_turnover="2",
        minimum_trade_notional="1",
        fee_buffer="0",
        mode="PAPER",
    )
    optimization = run_optimization(portfolio, "optimization-1", refresh_history=False)
    assert optimization.status == "COMPLETED"
    assert optimization.targets.count() == 2
    assert sum(target.optimized_weight for target in optimization.targets.all()) == pytest.approx(Decimal("0.90"), abs=Decimal("0.000001"))
    rebalance = plan_optimized_rebalance(
        optimization,
        "optimized-rebalance-1",
        mode="PAPER",
        strict_market_state=True,
    )
    assert rebalance.target_source == "PORTFOLIO_OPTIMIZATION"
    assert rebalance.optimization_run_id == optimization.pk
    assert OrderIntent.objects.filter(rebalance=rebalance).exists()
    assert PositionSizingDecision.objects.filter(order_intent__rebalance=rebalance).count() == OrderIntent.objects.filter(rebalance=rebalance).count()


def test_optimization_preview_api_returns_metrics_targets_and_shadow_trades(client):
    portfolio, _, _ = _optimization_case()
    RebalancePolicy.objects.create(portfolio=portfolio, maximum_turnover="2", minimum_trade_notional="1", fee_buffer="0")
    result = client.post(
        "/api/v1/portfolio-optimization/preview/",
        data={"portfolio_id": portfolio.pk, "refresh_history": False},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="api-optimization-preview",
    )
    assert result.status_code == 201
    body = result.json()["data"]
    assert body["status"] == "COMPLETED"
    assert body["expected_volatility"] is not None
    assert len(body["targets"]) == 2
    assert body["rebalance"]["mode"] == "SHADOW"
    assert body["planned_trades"]
    assert not OrderIntent.objects.exists()


@pytest.mark.parametrize("flow_type,amount,expected_nav,expected_cash", [
    ("DEPOSIT", "1000", Decimal("11000"), Decimal("11000")),
    ("WITHDRAWAL", "1000", Decimal("9000"), Decimal("9000")),
])
def test_deposits_and_withdrawals_recalculate_post_flow_optimized_weights(flow_type, amount, expected_nav, expected_cash):
    portfolio, _, _ = _optimization_case()
    strategy = TradingStrategy.objects.create(name=f"Flow strategy {flow_type}", strategy_type="fixed_weight", allocated_capital=10000)
    StrategyAllocation.objects.create(portfolio=portfolio, strategy=strategy, weight=1)
    allocation = create_flow(
        portfolio,
        flow_type,
        amount,
        f"flow-{flow_type.lower()}",
        allocation_mode="PORTFOLIO_OPTIMIZATION",
    )
    strategy.refresh_from_db()
    assert allocation.optimization_run.status == "COMPLETED"
    assert allocation.optimization_run.nav == expected_nav
    assert Decimal(allocation.snapshot["post_flow_cash"]) == expected_cash
    rebalance = allocation.optimization_run.rebalances.get()
    assert rebalance.mode == "SHADOW"
    assert rebalance.target_source == "PORTFOLIO_OPTIMIZATION"
    assert not OrderIntent.objects.filter(rebalance=rebalance).exists()
    assert strategy.allocated_capital == Decimal("10000")
    assert not AllocationDecision.objects.filter(run=allocation).exists()
    assert not StrategyCapitalSnapshot.objects.filter(allocation_run=allocation).exists()
    assert allocation.allocation_mode == "PORTFOLIO_OPTIMIZATION"
    assert allocation.approved_amount + allocation.unallocated_amount == Decimal(amount)
    assert allocation.status == ("COMPLETED" if allocation.unallocated_amount == 0 else "PARTIALLY_ALLOCATED")
    assert allocation.snapshot["optimization_run_id"] == allocation.optimization_run_id
    assert allocation.snapshot["rebalance_run_id"] == rebalance.pk


def test_auto_with_enabled_universe_and_policy_resolves_to_optimization():
    portfolio, _, _ = _optimization_case()
    RebalancePolicy.objects.create(portfolio=portfolio, maximum_turnover="2", minimum_trade_notional="1", fee_buffer="0")
    strategy = TradingStrategy.objects.create(name="Auto optimization strategy", strategy_type="fixed_weight", allocated_capital=321)
    StrategyAllocation.objects.create(portfolio=portfolio, strategy=strategy, weight=1)

    allocation = create_flow(portfolio, "DEPOSIT", "100", "flow-auto-optimization", allocation_mode="AUTO")

    strategy.refresh_from_db()
    assert allocation.allocation_mode == "PORTFOLIO_OPTIMIZATION"
    assert allocation.optimization_run_id is not None
    assert strategy.allocated_capital == Decimal("321")
    assert not allocation.decisions.exists()


def test_optimization_application_is_one_time_and_identical_retry_returns_existing(client):
    portfolio, _, _ = _optimization_case()
    RebalancePolicy.objects.create(portfolio=portfolio, maximum_turnover="2", minimum_trade_notional="1", fee_buffer="0")
    preview = client.post(
        "/api/v1/portfolio-optimization/preview/",
        data={"portfolio_id": portfolio.pk, "refresh_history": False},
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="preview-once",
    ).json()["data"]
    payload = json.dumps({
        "optimization_run_id": preview["id"],
        "portfolio_id": portfolio.pk,
        "policy_id": preview["policy_id"],
        "universe_id": preview["universe_id"],
    })

    first = client.post(
        "/api/v1/portfolio-optimization/run/",
        data=payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="apply-once",
    )
    retry = client.post(
        "/api/v1/portfolio-optimization/run/",
        data=payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="apply-once",
    )
    duplicate = client.post(
        "/api/v1/portfolio-optimization/run/",
        data=payload,
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="apply-again",
    )

    assert first.status_code == retry.status_code == 201
    assert first.json()["data"]["applied_rebalance"]["id"] == retry.json()["data"]["applied_rebalance"]["id"]
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "OPTIMIZATION_ALREADY_APPLIED"
    run = PortfolioOptimizationRun.objects.get(pk=preview["id"])
    assert run.application_status == "APPLIED"
    assert run.rebalances.count() == 2
    assert run.applied_rebalance.mode == "SHADOW"


def test_universe_size_is_rejected_on_save_and_revalidated_before_optimization(client):
    portfolio, instruments, _ = _optimization_case()
    extra = Instrument.objects.create(symbol="CCC")
    response = client.post(
        "/api/v1/portfolio-universe/",
        data=json.dumps({
            "portfolio_id": portfolio.pk,
            "instrument_ids": [instrument.pk for instrument in instruments] + [extra.pk],
            "maximum_instruments": 2,
        }),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNIVERSE_SIZE_EXCEEDED"
    assert response.json()["error"]["details"] == {"selected_count": 3, "maximum_instruments": 2}

    universe = PortfolioUniverse.objects.get(portfolio=portfolio)
    universe.maximum_instruments = 2
    universe.save(update_fields=["maximum_instruments"])
    PortfolioUniverseInstrument.objects.create(universe=universe, instrument=extra)
    with pytest.raises(UniverseSizeError, match="3.*2"):
        run_optimization(portfolio, "oversized-external-universe", refresh_history=False)


def test_portfolio_mutations_require_csrf_and_optimization_keeps_idempotency_protection():
    portfolio, _, _ = _optimization_case()
    browser = Client(enforce_csrf_checks=True)
    browser.get("/api/v1/system/")
    token = browser.cookies["csrftoken"].value
    blocked = browser.post(
        "/api/v1/portfolio-optimization/preview/",
        data=json.dumps({"portfolio_id": portfolio.pk, "refresh_history": False}),
        content_type="application/json",
        HTTP_IDEMPOTENCY_KEY="csrf-preview",
    )
    missing_key = browser.post(
        "/api/v1/portfolio-optimization/preview/",
        data=json.dumps({"portfolio_id": portfolio.pk, "refresh_history": False}),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )
    universe_blocked = browser.post(
        "/api/v1/portfolio-universe/",
        data=json.dumps({"portfolio_id": portfolio.pk, "instrument_ids": []}),
        content_type="application/json",
    )
    assert blocked.status_code == 403
    assert universe_blocked.status_code == 403
    assert missing_key.status_code == 400
    assert missing_key.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
