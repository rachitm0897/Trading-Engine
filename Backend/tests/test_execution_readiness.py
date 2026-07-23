from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.models import BrokerAccount
from apps.broker_gateway.models import BrokerGatewaySession
from apps.event_bus.models import StreamHealthMetric
from apps.execution.models import BrokerCommand
from apps.execution.readiness import (
    DEFAULT_REQUIRED_FLINK_JOBS,
    REQUIRED_WORKER_ROLES,
    collect_execution_readiness,
    record_worker_heartbeat,
)
from apps.instruments.models import Instrument
from apps.market_streams.models import (
    InstrumentMarketState,
    MarketBar,
    MarketDataSubscription,
    StrategyEvaluationJob,
)
from apps.oms.models import Order, OrderIntent
from apps.portfolios.models import TradingPortfolio
from apps.reconciliation.models import ReconciliationBreak, ReconciliationRun
from apps.strategies.models import (
    StrategyDefinition,
    StrategyInstance,
    StrategyVersion,
)


pytestmark = pytest.mark.django_db


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def healthy_flink(now, *, missing=(), stopped=(), checkpoint_age=5):
    jobs = []
    ids = {}
    for index, name in enumerate(DEFAULT_REQUIRED_FLINK_JOBS, start=1):
        if name in missing:
            continue
        job_id = f"job-{index}"
        ids[job_id] = name
        jobs.append(
            {
                "jid": job_id,
                "name": name,
                "state": "FAILED" if name in stopped else "RUNNING",
            }
        )

    def get(url, timeout):
        if url.endswith("/jobs/overview"):
            return JsonResponse({"jobs": jobs})
        job_id = url.split("/jobs/", 1)[1].split("/", 1)[0]
        assert job_id in ids
        checkpoint_at = now - timedelta(seconds=checkpoint_age)
        return JsonResponse(
            {
                "latest": {
                    "completed": {
                        "id": 7,
                        "status": "COMPLETED",
                        "latest_ack_timestamp": int(
                            checkpoint_at.timestamp() * 1000
                        ),
                    }
                }
            }
        )

    return get


def healthy_runtime(settings):
    settings.KAFKA_ENABLED = True
    settings.NEW_EXECUTION_MODE = "PAPER"
    settings.EXECUTION_REQUIRED_FLINK_JOBS = DEFAULT_REQUIRED_FLINK_JOBS
    settings.FLINK_CHECKPOINT_STALE_SECONDS = 180
    settings.MARKET_RAW_PRODUCER_HEARTBEAT_STALE_SECONDS = 30
    settings.MARKET_CONSUMER_HEARTBEAT_STALE_SECONDS = 30
    settings.EXECUTION_WORKER_HEARTBEAT_STALE_SECONDS = 30
    settings.GATEWAY_CONNECTIVITY_STALE_SECONDS = 30
    settings.STRATEGY_JOB_BACKLOG_THRESHOLD = 100
    settings.TARGET_COORDINATION_BACKLOG_THRESHOLD = 100
    settings.PENDING_INTENT_MAX_AGE_SECONDS = 60
    settings.BROKER_COMMAND_MAX_AGE_SECONDS = 60
    StreamHealthMetric.objects.create(
        component="market-raw-producer",
        metric="heartbeat",
        status="HEALTHY",
        value={"producer": "test"},
    )
    StreamHealthMetric.objects.create(
        component="backend-market-consumer",
        metric="heartbeat",
        status="HEALTHY",
        value={"consumer": "test"},
    )
    for role in REQUIRED_WORKER_ROLES:
        record_worker_heartbeat(role, worker=f"{role}@test")


def paper_scope(now):
    account = BrokerAccount.objects.create(
        account_id="DU-READINESS",
        net_liquidation=100000,
        available_cash=100000,
        is_reconciled=True,
    )
    session = BrokerGatewaySession.objects.create(
        display_name="Readiness Gateway",
        username_hint="paper",
        mode="paper",
        status=BrokerGatewaySession.Status.CONNECTED,
        child_container_name="readiness-gateway",
        internal_base_url="http://readiness-gateway:8080/api/v1",
        encrypted_gateway_token="encrypted",
        encrypted_novnc_password="encrypted",
        commands_enabled=True,
        last_gateway_state={"connected": True, "reconciled": True},
        last_checked_at=now,
    )
    portfolio = TradingPortfolio.objects.create(
        name="Readiness Portfolio",
        account=account,
        gateway_session=session,
    )
    instrument = Instrument.objects.create(symbol="READY")
    definition = StrategyDefinition.objects.create(
        key="READINESS",
        name="Readiness",
        plugin_path="tests.strategy_plugin_fixture.Readiness",
    )
    strategy = StrategyInstance.objects.create(
        name="Readiness Strategy",
        definition=definition,
        portfolio=portfolio,
        instrument=instrument,
        timeframe="1m",
        execution_mode="PAPER",
        state="FLAT",
        enabled=True,
    )
    version = StrategyVersion.objects.create(
        strategy_instance=strategy,
        version=1,
        configuration_snapshot={},
        parameter_hash="readiness",
        activated_at=now,
    )
    InstrumentMarketState.objects.create(
        instrument=instrument,
        status="FRESH",
        reference_price=100,
        latest_event_at=now,
        watermark_at=now,
        stale_after_seconds=300,
    )
    MarketDataSubscription.objects.create(
        instrument=instrument,
        gateway_session=session,
        conid=12345,
        timeframe="1m",
        state="ACTIVE",
        consumer_count=1,
        last_event_at=now,
    )
    bar = MarketBar.objects.create(
        instrument=instrument,
        bar_id="readiness-bar",
        interval="1m",
        window_start=now - timedelta(minutes=1),
        window_end=now,
        open=100,
        high=101,
        low=99,
        close=100,
        volume=1000,
        version=1,
        is_final=True,
        produced_at=now,
    )
    return account, session, portfolio, instrument, strategy, version, bar


def blocker_codes(result):
    return {item["code"] for item in result["blockers"]}


def test_execution_readiness_endpoint_reports_all_healthy_signals(
    client, settings, monkeypatch
):
    healthy_runtime(settings)
    now = timezone.now()
    monkeypatch.setattr(
        "apps.execution.readiness.requests.get", healthy_flink(now)
    )

    response = client.get("/api/v1/execution/readiness/")

    assert response.status_code == 200
    result = response.json()["data"]
    assert result["ready"] is True
    assert result["automatic_execution_ready"] is True
    assert result["signals"]["flink"]["running_jobs"] == sorted(
        DEFAULT_REQUIRED_FLINK_JOBS
    )
    assert all(
        item["checkpoint_id"] == 7
        for item in result["signals"]["flink"]["jobs"]
    )
    assert result["signals"]["workers"].keys() == set(REQUIRED_WORKER_ROLES)
    assert result["signals"]["gateway"]["status"] == "NOT_REQUIRED"


def test_missing_required_flink_job_and_checkpoint_are_blocking(settings):
    healthy_runtime(settings)
    now = timezone.now()
    result = collect_execution_readiness(
        http_get=healthy_flink(
            now,
            missing={"indicator-computation-v2"},
            checkpoint_age=300,
        ),
        now=now,
    )

    codes = blocker_codes(result)
    assert result["ready"] is False
    assert "REQUIRED_FLINK_JOBS_MISSING" in codes
    assert "FLINK_CHECKPOINT_STALE" in codes
    assert result["signals"]["flink"]["missing_jobs"] == [
        "indicator-computation-v2"
    ]


def test_worker_heartbeat_and_strategy_backlog_block_readiness(settings):
    healthy_runtime(settings)
    now = timezone.now()
    _, _, _, _, strategy, version, bar = paper_scope(now)
    settings.STRATEGY_JOB_BACKLOG_THRESHOLD = 0
    StrategyEvaluationJob.objects.create(
        strategy_instance=strategy,
        strategy_version=version,
        bar=bar,
        market_bar_id=bar.bar_id,
        bar_version=bar.version,
        event_id="readiness-event",
        event_time=now,
        source_data_version=1,
        expected_input_identity_hashes=[],
        status="PENDING",
        idempotency_key="readiness-evaluation-job",
    )
    stale = StreamHealthMetric.objects.get(
        component="execution-worker", metric="intent_execution"
    )
    StreamHealthMetric.objects.filter(pk=stale.pk).update(
        observed_at=now - timedelta(minutes=5)
    )

    result = collect_execution_readiness(http_get=healthy_flink(now), now=now)

    codes = blocker_codes(result)
    assert "EXECUTION_WORKERS_ABSENT" in codes
    assert "STRATEGY_JOB_BACKLOG_EXCEEDED" in codes
    assert result["signals"]["strategy_job_backlog"]["count"] == 1
    assert (
        result["signals"]["workers"]["intent_execution"]["status"] == "STALE"
    )


def test_stale_market_unreconciled_gateway_and_uncertain_order_block_portfolio(
    settings,
):
    healthy_runtime(settings)
    now = timezone.now()
    account, session, portfolio, instrument, _, _, _ = paper_scope(now)
    InstrumentMarketState.objects.filter(instrument=instrument).update(
        latest_event_at=now - timedelta(hours=1)
    )
    session.last_gateway_state = {"connected": True, "reconciled": False}
    session.save(update_fields=["last_gateway_state", "updated_at"])
    account.is_reconciled = False
    account.save(update_fields=["is_reconciled", "updated_at"])
    run = ReconciliationRun.objects.create(
        broker_account=account,
        gateway_session=session,
        trigger="readiness",
        status="FAILED",
    )
    ReconciliationBreak.objects.create(
        run=run,
        category="ORDER",
        severity="ERROR",
        material=True,
        resolved=False,
    )
    intent = OrderIntent.objects.create(
        portfolio=portfolio,
        instrument=instrument,
        side="BUY",
        quantity=1,
        reference_price=100,
        idempotency_key="readiness-intent",
        operation_status="QUEUED",
        source="REBALANCE",
        mode="PAPER",
    )
    order = Order.objects.create(
        intent=intent,
        internal_id="readiness-order",
        status="UNKNOWN",
        quantity=1,
    )
    BrokerCommand.objects.create(
        order=order,
        internal_order_id=order.internal_id,
        gateway_session=session,
        command_type=BrokerCommand.CommandType.PLACE,
        idempotency_key="readiness-command",
        request_payload={"internal_id": order.internal_id},
        request_hash="readiness-command-hash",
        status=BrokerCommand.Status.UNCERTAIN,
        uncertainty_reason="response lost",
    )

    result = collect_execution_readiness(http_get=healthy_flink(now), now=now)

    codes = blocker_codes(result)
    assert "MARKET_DATA_STALE" in codes
    assert "GATEWAY_NOT_RECONCILED" in codes
    assert "BROKER_RECONCILIATION_NOT_READY" in codes
    assert "UNRESOLVED_UNCERTAIN_ORDER" in codes
    assert result["signals"]["broker_commands"]["scoped_uncertain_count"] == 1
    assert result["signals"]["broker_reconciliation"][
        "unresolved_material_breaks"
    ] == 1
