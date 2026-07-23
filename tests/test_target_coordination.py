from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from apps.accounts.models import BrokerAccount
from apps.allocation.models import (
    PortfolioTargetCoordination,
    PortfolioTargetSnapshot,
    RebalancePolicy,
    RebalanceRun,
)
from apps.instruments.models import BrokerContract, Instrument
from apps.market_streams.models import InstrumentMarketState
from apps.oms.models import Order, OrderIntent
from apps.portfolios.models import PortfolioPosition, TradingPortfolio
from apps.rebalancing.coordinator import (
    build_portfolio_target_snapshot,
    coordinate_portfolio,
    mark_portfolio_for_target_coordination,
    process_target_coordination,
)
from apps.rebalancing.services import advance_rebalance, plan_rebalance
from apps.strategies.models import (
    StrategyAllocation,
    StrategyAttributedPosition,
    StrategyDefinition,
    StrategyInstance,
    StrategyRun,
    StrategyTarget,
    StrategyVersion,
)


pytestmark = pytest.mark.django_db


def make_portfolio(name="Coordinated", *, mode="PAPER"):
    account = BrokerAccount.objects.create(
        account_id=f"DU-{name}",
        net_liquidation=10000,
        available_cash=10000,
        is_reconciled=True,
    )
    portfolio = TradingPortfolio.objects.create(name=name, account=account)
    RebalancePolicy.objects.create(
        portfolio=portfolio,
        mode=mode,
        instrument_drift_threshold=0,
        minimum_trade_notional=1,
        fee_buffer=0,
        cash_buffer_percent=0,
        maximum_turnover=2,
    )
    return portfolio


def make_instrument(symbol):
    instrument = Instrument.objects.create(symbol=symbol, exchange="SMART", currency="USD")
    BrokerContract.objects.create(
        instrument=instrument,
        conid=100000 + instrument.pk,
        primary_exchange="NASDAQ",
        local_symbol=symbol,
    )
    InstrumentMarketState.objects.create(
        instrument=instrument,
        status="FRESH",
        reference_price=100,
        latest_event_at=timezone.now(),
        stale_after_seconds=3600,
    )
    return instrument


def make_strategy(
    portfolio,
    instrument,
    name,
    *,
    weight="0.10",
    signal_time=None,
    state="LONG",
    enabled=True,
    mode="PAPER",
    version_number=1,
):
    instance = StrategyInstance.objects.create(
        name=name,
        definition=StrategyDefinition.objects.get(key="FIXED_WEIGHT_REBALANCE"),
        portfolio=portfolio,
        instrument=instrument,
        timeframe="5m",
        parameters={"direction": "BOTH"},
        target_configuration={"target_weight": weight},
        execution_mode=mode,
        state=state,
        enabled=enabled,
        version=version_number,
    )
    version = StrategyVersion.objects.create(
        strategy_instance=instance,
        version=version_number,
        configuration_snapshot={},
        parameter_hash=f"version-{instance.pk}-{version_number}",
    )
    StrategyAllocation.objects.create(
        strategy_instance=instance,
        portfolio=portfolio,
        weight=1,
    )
    run = StrategyRun.objects.create(
        strategy_instance=instance,
        strategy_version=version,
        input_hash=f"input-{instance.pk}-{version_number}",
        status="COMPLETED",
        completed_at=signal_time or timezone.now(),
    )
    target = StrategyTarget.objects.create(
        run=run,
        strategy_instance=instance,
        strategy_version=version,
        portfolio=portfolio,
        instrument=instrument,
        target_weight=weight,
        signal_time=signal_time or timezone.now(),
    )
    return instance, version, run, target


def add_target(instance, version, weight, when, suffix):
    run = StrategyRun.objects.create(
        strategy_instance=instance,
        strategy_version=version,
        input_hash=f"input-{instance.pk}-{suffix}",
        status="COMPLETED",
        completed_at=when,
    )
    return StrategyTarget.objects.create(
        run=run,
        strategy_instance=instance,
        strategy_version=version,
        portfolio=instance.portfolio,
        instrument=instance.instrument,
        target_weight=weight,
        signal_time=when,
    )


def test_five_strategy_targets_for_one_bar_create_one_reproducible_snapshot():
    portfolio = make_portfolio("five", mode="SHADOW")
    instrument = make_instrument("FIVE")
    event_time = timezone.now()
    for index in range(5):
        make_strategy(
            portfolio,
            instrument,
            f"strategy-{index}",
            weight="0.02",
            signal_time=event_time,
            mode="SHADOW",
        )

    snapshot = build_portfolio_target_snapshot(portfolio, logical_time=event_time)
    run = plan_rebalance(
        portfolio,
        "STRATEGY_TARGETS",
        "five-targets",
        target_snapshot=snapshot,
        automatic=True,
    )

    assert snapshot.status == "READY"
    assert len(snapshot.source_strategy_runs) == 5
    assert len(snapshot.target_contributions) == 5
    assert Decimal(snapshot.net_targets[str(instrument.pk)]) == Decimal("0.10")
    assert run.target_snapshot == snapshot
    assert run.snapshot["target_snapshot_id"] == snapshot.pk
    snapshot.status = "REJECTED"
    with pytest.raises(ValidationError, match="immutable"):
        snapshot.save()


@override_settings(PORTFOLIO_TARGET_COORDINATION_DEBOUNCE_SECONDS=0)
def test_simultaneous_target_marks_serialize_one_automatic_rebalance():
    portfolio = make_portfolio("simultaneous")
    instrument = make_instrument("SIM")
    _, _, _, target = make_strategy(portfolio, instrument, "sim-one")
    mark_portfolio_for_target_coordination(portfolio.pk, logical_event_time=target.signal_time)
    mark_portfolio_for_target_coordination(portfolio.pk, logical_event_time=target.signal_time)

    first = coordinate_portfolio(portfolio.pk)
    second = coordinate_portfolio(portfolio.pk)

    assert first.pk == second.pk
    assert RebalanceRun.objects.filter(
        portfolio=portfolio,
        automatic=True,
        status__in=["QUEUED", "CALCULATING", "INTENTS_CREATED", "EXECUTING"],
    ).count() == 1
    assert not PortfolioTargetCoordination.objects.get(
        portfolio=portfolio
    ).pending_recalculation


@override_settings(PORTFOLIO_TARGET_MAX_AGE_SECONDS=60)
def test_stale_target_is_rejected_and_cannot_create_orders():
    portfolio = make_portfolio("stale")
    instrument = make_instrument("STALE")
    old = timezone.now() - timedelta(minutes=10)
    make_strategy(portfolio, instrument, "stale-strategy", signal_time=old)

    snapshot = build_portfolio_target_snapshot(portfolio)

    assert snapshot.status == "REJECTED"
    assert snapshot.rejected_targets[0]["reason"] == "STALE_TARGET"
    with pytest.raises(ValueError, match="Rejected"):
        plan_rebalance(
            portfolio,
            "STRATEGY_TARGETS",
            "stale-rebalance",
            target_snapshot=snapshot,
            automatic=True,
        )
    assert not OrderIntent.objects.filter(portfolio=portfolio, source="REBALANCE").exists()


def test_old_strategy_version_target_is_rejected():
    portfolio = make_portfolio("old-version")
    instrument = make_instrument("OLDV")
    instance, old_version, _, _ = make_strategy(
        portfolio,
        instrument,
        "versioned",
    )
    instance.version = 2
    instance.save(update_fields=["version"])
    StrategyVersion.objects.create(
        strategy_instance=instance,
        version=2,
        configuration_snapshot={},
        parameter_hash="current-version",
    )

    snapshot = build_portfolio_target_snapshot(portfolio)

    assert snapshot.status == "REJECTED"
    assert snapshot.rejected_targets[0]["reason"] == "INACTIVE_STRATEGY_VERSION"
    assert snapshot.strategy_versions[str(instance.pk)] != old_version.pk


def test_event_time_selection_wins_over_row_creation_time():
    portfolio = make_portfolio("event-time", mode="SHADOW")
    instrument = make_instrument("EVENT")
    now = timezone.now()
    instance, version, _, newest_event = make_strategy(
        portfolio,
        instrument,
        "event-aware",
        weight="0.20",
        signal_time=now,
        mode="SHADOW",
    )
    older_event = add_target(
        instance,
        version,
        "0.80",
        now - timedelta(seconds=10),
        "created-later",
    )

    snapshot = build_portfolio_target_snapshot(portfolio)

    assert snapshot.target_contributions[0]["target_id"] == newest_event.pk
    assert snapshot.target_contributions[0]["target_id"] != older_event.pk
    assert Decimal(snapshot.net_targets[str(instrument.pk)]) == Decimal("0.20")


def test_existing_open_buy_is_in_projected_exposure():
    portfolio = make_portfolio("open-buy")
    instrument = make_instrument("OPENBUY")
    make_strategy(portfolio, instrument, "open-buy-strategy", weight="0.10")
    existing_intent = OrderIntent.objects.create(
        portfolio=portfolio,
        instrument=instrument,
        side="BUY",
        quantity=4,
        idempotency_key="existing-open-buy",
    )
    Order.objects.create(
        intent=existing_intent,
        internal_id="existing-open-buy-order",
        status="ACKNOWLEDGED",
        quantity=4,
    )

    snapshot = build_portfolio_target_snapshot(portfolio)
    run = plan_rebalance(
        portfolio,
        "STRATEGY_TARGETS",
        "project-open-buy",
        target_snapshot=snapshot,
    )

    position = snapshot.current_positions[str(instrument.pk)]
    assert Decimal(position["projected_quantity"]) == Decimal("4")
    assert OrderIntent.objects.get(rebalance=run).quantity == Decimal("6")


def test_pending_sell_followed_by_buy_target_rebalances_projected_exposure():
    portfolio = make_portfolio("pending-sell")
    instrument = make_instrument("PENDSELL")
    PortfolioPosition.objects.create(
        portfolio=portfolio,
        instrument=instrument,
        quantity=10,
        market_price=100,
    )
    make_strategy(portfolio, instrument, "pending-sell-strategy", weight="0.10")
    OrderIntent.objects.create(
        portfolio=portfolio,
        instrument=instrument,
        side="SELL",
        quantity=5,
        idempotency_key="pending-sell-intent",
        operation_status="PENDING",
    )

    snapshot = build_portfolio_target_snapshot(portfolio)
    run = plan_rebalance(
        portfolio,
        "STRATEGY_TARGETS",
        "pending-sell-new-buy",
        target_snapshot=snapshot,
    )

    position = snapshot.current_positions[str(instrument.pk)]
    assert Decimal(position["filled_quantity"]) == Decimal("10")
    assert Decimal(position["reserved_signed_order_intents"]) == Decimal("-5")
    intent = OrderIntent.objects.get(rebalance=run)
    assert intent.side == "BUY"
    assert intent.quantity == Decimal("5")


@override_settings(PORTFOLIO_TARGET_COORDINATION_DEBOUNCE_SECONDS=0)
def test_target_update_during_active_rebalance_runs_after_safe_boundary():
    portfolio = make_portfolio("recalculate")
    instrument = make_instrument("RECALC")
    instance, version, _, first_target = make_strategy(
        portfolio,
        instrument,
        "recalculate-strategy",
        weight="0.10",
    )
    mark_portfolio_for_target_coordination(
        portfolio.pk, logical_event_time=first_target.signal_time
    )
    first_run = coordinate_portfolio(portfolio.pk)
    first_intent = OrderIntent.objects.get(rebalance=first_run)
    later = timezone.now() + timedelta(seconds=1)
    add_target(instance, version, "0.20", later, "later")
    mark_portfolio_for_target_coordination(portfolio.pk, logical_event_time=later)
    assert PortfolioTargetCoordination.objects.get(
        portfolio=portfolio
    ).pending_recalculation

    PortfolioPosition.objects.update_or_create(
        portfolio=portfolio,
        instrument=instrument,
        defaults={"quantity": first_intent.quantity, "market_price": 100},
    )
    Order.objects.create(
        intent=first_intent,
        internal_id="first-coordinated-order",
        status="FILLED",
        quantity=first_intent.quantity,
        filled_quantity=first_intent.quantity,
    )
    advance_rebalance(first_run)
    process_target_coordination()

    runs = RebalanceRun.objects.filter(portfolio=portfolio, automatic=True).order_by("pk")
    assert runs.count() == 2
    assert runs.first().status == "COMPLETED"
    assert runs.last().target_snapshot_id != runs.first().target_snapshot_id


def test_paused_strategy_retains_existing_attributed_position():
    portfolio = make_portfolio("paused", mode="SHADOW")
    instrument = make_instrument("PAUSED")
    instance, _, _, _ = make_strategy(
        portfolio,
        instrument,
        "paused-strategy",
        state="PAUSED",
        enabled=False,
        mode="SHADOW",
    )
    StrategyAttributedPosition.objects.create(
        strategy_instance=instance,
        portfolio=portfolio,
        instrument=instrument,
        quantity=5,
    )
    PortfolioPosition.objects.create(
        portfolio=portfolio,
        instrument=instrument,
        quantity=5,
        market_price=100,
    )

    snapshot = build_portfolio_target_snapshot(portfolio)
    run = plan_rebalance(
        portfolio,
        "STRATEGY_TARGETS",
        "paused-hold",
        target_snapshot=snapshot,
        automatic=True,
    )

    contribution = snapshot.target_contributions[0]
    assert contribution["lifecycle"] == "PAUSED"
    assert contribution["lifecycle_policy"] == "HOLD"
    assert Decimal(snapshot.net_targets[str(instrument.pk)]) == Decimal("0.05")
    assert run.targets.get(instrument=instrument).trade_quantity == 0


def test_flatten_requested_targets_zero_through_common_rebalance():
    portfolio = make_portfolio("flatten")
    instrument = make_instrument("FLATTEN")
    instance, _, _, _ = make_strategy(
        portfolio,
        instrument,
        "flatten-strategy",
        weight="0",
        state="FLATTEN_REQUESTED",
    )
    StrategyAttributedPosition.objects.create(
        strategy_instance=instance,
        portfolio=portfolio,
        instrument=instrument,
        quantity=5,
    )
    PortfolioPosition.objects.create(
        portfolio=portfolio,
        instrument=instrument,
        quantity=5,
        market_price=100,
    )

    snapshot = build_portfolio_target_snapshot(portfolio)
    run = plan_rebalance(
        portfolio,
        "STRATEGY_TARGETS",
        "flatten-through-snapshot",
        target_snapshot=snapshot,
        automatic=True,
    )

    assert snapshot.target_contributions[0]["lifecycle_policy"] == "FLATTEN"
    assert Decimal(snapshot.net_targets[str(instrument.pk)]) == 0
    intent = OrderIntent.objects.get(rebalance=run)
    assert intent.side == "SELL"
    assert intent.quantity == 5
    assert intent.attributions.get().allocated_quantity == Decimal("-5")
