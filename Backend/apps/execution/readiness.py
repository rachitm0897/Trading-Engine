from __future__ import annotations

from datetime import datetime, timezone as datetime_timezone
from typing import Any, Callable

import requests
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import BrokerAccount
from apps.allocation.models import PortfolioTargetCoordination, RebalanceRun
from apps.broker_gateway.models import BrokerGatewaySession
from apps.event_bus.models import StreamHealthMetric
from apps.market_streams.models import (
    InstrumentMarketState,
    MarketDataSubscription,
    StrategyEvaluationJob,
)
from apps.oms.models import OrderIntent
from apps.reconciliation.models import ReconciliationBreak
from apps.strategies.models import StrategyInstance

from .models import BrokerCommand


DEFAULT_REQUIRED_FLINK_JOBS = (
    "market-normalization-v2",
    "bar-aggregation-v2",
    "indicator-computation-v2",
    "stale-price-detection-v1",
    "stream-health-v1",
)
REQUIRED_WORKER_ROLES = (
    "strategy_evaluation",
    "target_coordination",
    "intent_execution",
    "broker_commands",
)
ACTIVE_STRATEGY_JOB_STATUSES = (
    "WAITING_FOR_INPUT",
    "PENDING",
    "CLAIMED",
    "RUNNING",
    "RETRY",
)
ACTIVE_REBALANCE_STATUSES = (
    "QUEUED",
    "CALCULATING",
    "INTENTS_CREATED",
    "EXECUTING",
)
PENDING_INTENT_STATUSES = ("PENDING", "CLAIMED")
PENDING_BROKER_COMMAND_STATUSES = (
    BrokerCommand.Status.PENDING,
    BrokerCommand.Status.CLAIMED,
    BrokerCommand.Status.SENDING,
    BrokerCommand.Status.RETRY,
    BrokerCommand.Status.UNCERTAIN,
)
HEALTHY_HEARTBEAT_STATUSES = {"HEALTHY", "RUNNING", "IDLE"}


def _setting_tuple(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = getattr(settings, name, default)
    if isinstance(value, str):
        value = value.split(",")
    normalized = tuple(str(item).strip() for item in value if str(item).strip())
    return normalized or default


def _age_seconds(value, now):
    if value is None:
        return None
    return round(max(0.0, (now - value).total_seconds()), 3)


def _oldest_age(queryset, field: str, now):
    value = queryset.order_by(field).values_list(field, flat=True).first()
    return value, _age_seconds(value, now)


def _heartbeat_signal(metric, *, stale_seconds: int, now):
    observed_at = metric.observed_at if metric else None
    age = _age_seconds(observed_at, now)
    healthy = bool(
        metric
        and metric.status in HEALTHY_HEARTBEAT_STATUSES
        and age is not None
        and age <= stale_seconds
    )
    if metric is None:
        status = "MISSING"
    elif age is None or age > stale_seconds:
        status = "STALE"
    elif metric.status not in HEALTHY_HEARTBEAT_STATUSES:
        status = "DEGRADED"
    else:
        status = "HEALTHY"
    return {
        "status": status,
        "healthy": healthy,
        "last_heartbeat": observed_at,
        "age_seconds": age,
        "stale_after_seconds": stale_seconds,
        "reported_status": metric.status if metric else None,
        "value": metric.value if metric else {},
    }


def record_worker_heartbeat(
    role: str,
    *,
    status: str = "HEALTHY",
    worker: str = "",
    details: dict[str, Any] | None = None,
):
    """Record proof that the worker consuming a required execution queue ran."""
    normalized = str(role or "").strip().lower()
    if normalized not in REQUIRED_WORKER_ROLES:
        raise ValueError(f"Unknown execution worker role: {role}")
    value = {"worker": str(worker or "")}
    if details:
        value.update(details)
    metric, _ = StreamHealthMetric.objects.update_or_create(
        component="execution-worker",
        metric=normalized,
        defaults={"status": str(status or "UNKNOWN").upper(), "value": value},
    )
    return metric


def _timestamp_from_millis(value):
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000, tz=datetime_timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _completed_checkpoint(payload):
    latest = (payload or {}).get("latest") or {}
    completed = latest.get("completed")
    if completed:
        return completed
    history = [
        item
        for item in ((payload or {}).get("history") or [])
        if str(item.get("status") or "").upper() == "COMPLETED"
    ]
    return max(
        history,
        key=lambda item: item.get("latest_ack_timestamp")
        or item.get("trigger_timestamp")
        or 0,
        default=None,
    )


def _flink_readiness(
    *,
    http_get: Callable[..., Any],
    required_jobs: tuple[str, ...],
    checkpoint_stale_seconds: int,
    request_timeout_seconds: float,
    now,
):
    signal = {
        "status": "DEGRADED",
        "required_jobs": list(required_jobs),
        "running_jobs": [],
        "missing_jobs": [],
        "not_running_jobs": [],
        "jobs": [],
        "latest_checkpoint": None,
        "oldest_checkpoint": None,
        "oldest_checkpoint_age_seconds": None,
        "checkpoint_stale_after_seconds": checkpoint_stale_seconds,
    }
    blockers = []
    try:
        response = http_get(
            settings.FLINK_REST_URL.rstrip("/") + "/jobs/overview",
            timeout=request_timeout_seconds,
        )
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        jobs = (response.json() or {}).get("jobs") or []
        by_name = {str(item.get("name") or ""): item for item in jobs}
        signal["running_jobs"] = sorted(
            name
            for name in required_jobs
            if name in by_name and by_name[name].get("state") == "RUNNING"
        )
        signal["missing_jobs"] = sorted(name for name in required_jobs if name not in by_name)
        signal["not_running_jobs"] = sorted(
            name
            for name in required_jobs
            if name in by_name and by_name[name].get("state") != "RUNNING"
        )
        if signal["missing_jobs"]:
            blockers.append(
                {
                    "code": "REQUIRED_FLINK_JOBS_MISSING",
                    "message": "One or more required Flink jobs are missing",
                    "details": {"jobs": signal["missing_jobs"]},
                }
            )
        if signal["not_running_jobs"]:
            blockers.append(
                {
                    "code": "REQUIRED_FLINK_JOBS_NOT_RUNNING",
                    "message": "One or more required Flink jobs are not running",
                    "details": {"jobs": signal["not_running_jobs"]},
                }
            )

        checkpoint_times = []
        for name in required_jobs:
            job = by_name.get(name)
            row = {
                "name": name,
                "job_id": (job or {}).get("jid") or (job or {}).get("id"),
                "state": (job or {}).get("state") or "MISSING",
                "checkpoint_id": None,
                "checkpoint_at": None,
                "checkpoint_age_seconds": None,
            }
            if row["job_id"] and row["state"] == "RUNNING":
                checkpoint_response = http_get(
                    settings.FLINK_REST_URL.rstrip("/")
                    + f"/jobs/{row['job_id']}/checkpoints",
                    timeout=request_timeout_seconds,
                )
                if hasattr(checkpoint_response, "raise_for_status"):
                    checkpoint_response.raise_for_status()
                completed = _completed_checkpoint(checkpoint_response.json())
                if completed:
                    checkpoint_at = _timestamp_from_millis(
                        completed.get("latest_ack_timestamp")
                        or completed.get("trigger_timestamp")
                    )
                    row.update(
                        {
                            "checkpoint_id": completed.get("id"),
                            "checkpoint_at": checkpoint_at,
                            "checkpoint_age_seconds": _age_seconds(checkpoint_at, now),
                        }
                    )
                    if checkpoint_at:
                        checkpoint_times.append(checkpoint_at)
            signal["jobs"].append(row)

        missing_checkpoints = [
            item["name"]
            for item in signal["jobs"]
            if item["state"] == "RUNNING" and item["checkpoint_at"] is None
        ]
        stale_checkpoints = [
            item["name"]
            for item in signal["jobs"]
            if item["checkpoint_age_seconds"] is not None
            and item["checkpoint_age_seconds"] > checkpoint_stale_seconds
        ]
        if missing_checkpoints:
            blockers.append(
                {
                    "code": "FLINK_CHECKPOINT_MISSING",
                    "message": "A required Flink job has no completed checkpoint",
                    "details": {"jobs": missing_checkpoints},
                }
            )
        if stale_checkpoints:
            blockers.append(
                {
                    "code": "FLINK_CHECKPOINT_STALE",
                    "message": "A required Flink job checkpoint is stale",
                    "details": {"jobs": stale_checkpoints},
                }
            )
        if checkpoint_times:
            signal["latest_checkpoint"] = max(checkpoint_times)
            signal["oldest_checkpoint"] = min(checkpoint_times)
            signal["oldest_checkpoint_age_seconds"] = _age_seconds(
                signal["oldest_checkpoint"], now
            )
        signal["status"] = "HEALTHY" if not blockers else "DEGRADED"
    except Exception as exc:
        signal["error"] = str(exc)[:255]
        blockers.append(
            {
                "code": "FLINK_UNAVAILABLE",
                "message": "Flink readiness could not be inspected",
                "details": {"error": str(exc)[:255]},
            }
        )
    return signal, blockers


def _paper_scope(now):
    strategies = list(
        StrategyInstance.objects.filter(enabled=True, execution_mode="PAPER")
        .select_related("portfolio__account", "portfolio__gateway_session", "instrument")
        .order_by("pk")
    )
    portfolio_ids = sorted({item.portfolio_id for item in strategies})
    instrument_ids = sorted({item.instrument_id for item in strategies})
    account_ids = sorted({item.portfolio.account_id for item in strategies})
    session_ids = sorted(
        {
            item.portfolio.gateway_session_id
            for item in strategies
            if item.portfolio.gateway_session_id
        },
        key=str,
    )

    market_states = {
        item.instrument_id: item
        for item in InstrumentMarketState.objects.filter(instrument_id__in=instrument_ids)
    }
    subscriptions = {}
    if strategies:
        for item in MarketDataSubscription.objects.filter(
            instrument_id__in=instrument_ids
        ):
            subscriptions[
                (item.gateway_session_id, item.instrument_id, item.timeframe)
            ] = item
    stale_strategies = []
    for strategy in strategies:
        state = market_states.get(strategy.instrument_id)
        subscription = subscriptions.get(
            (
                strategy.portfolio.gateway_session_id,
                strategy.instrument_id,
                strategy.timeframe,
            )
        ) or subscriptions.get((None, strategy.instrument_id, strategy.timeframe))
        state_usable = bool(state and state.is_usable(now))
        subscription_age = _age_seconds(
            subscription.last_event_at if subscription else None, now
        )
        interval_seconds = {
            "5s": 5,
            "1m": 60,
            "5m": 300,
            "15m": 900,
            "1h": 3600,
            "1d": 86400,
        }.get(strategy.timeframe, 60)
        subscription_stale_after = max(
            int(getattr(settings, "MARKET_PRICE_STALE_SECONDS", 300)),
            interval_seconds * 2 + 60,
        )
        subscription_usable = bool(
            subscription
            and subscription.state in {"ACTIVE", "DEGRADED"}
            and subscription_age is not None
            and subscription_age <= subscription_stale_after
        )
        if not state_usable or not subscription_usable:
            stale_strategies.append(
                {
                    "strategy_id": strategy.pk,
                    "portfolio_id": strategy.portfolio_id,
                    "instrument_id": strategy.instrument_id,
                    "timeframe": strategy.timeframe,
                    "market_state": state.status if state else "MISSING",
                    "last_market_event": state.latest_event_at if state else None,
                    "subscription_state": subscription.state
                    if subscription
                    else "MISSING",
                    "last_raw_event": subscription.last_event_at
                    if subscription
                    else None,
                }
            )
    return {
        "strategies": strategies,
        "strategy_count": len(strategies),
        "portfolio_ids": portfolio_ids,
        "instrument_ids": instrument_ids,
        "account_ids": account_ids,
        "session_ids": session_ids,
        "stale_strategies": stale_strategies,
    }


def _gateway_and_reconciliation(scope, now):
    portfolio_ids = scope["portfolio_ids"]
    strategies = scope["strategies"]
    if not strategies:
        return (
            {
                "status": "NOT_REQUIRED",
                "required_session_count": 0,
                "sessions": [],
            },
            {
                "status": "NOT_REQUIRED",
                "account_count": 0,
                "accounts": [],
                "unresolved_material_breaks": 0,
            },
            [],
        )

    gateway_stale_seconds = int(
        getattr(settings, "GATEWAY_CONNECTIVITY_STALE_SECONDS", 30)
    )
    sessions = {
        item.pk: item
        for item in BrokerGatewaySession.objects.filter(pk__in=scope["session_ids"])
    }
    portfolios_by_session = {}
    missing_session_portfolios = []
    for strategy in strategies:
        session_id = strategy.portfolio.gateway_session_id
        if session_id is None:
            missing_session_portfolios.append(strategy.portfolio_id)
        else:
            portfolios_by_session.setdefault(session_id, set()).add(
                strategy.portfolio_id
            )

    session_rows = []
    bad_connectivity = []
    bad_gateway_reconciliation = []
    for session_id, scoped_portfolios in sorted(
        portfolios_by_session.items(), key=lambda item: str(item[0])
    ):
        session = sessions.get(session_id)
        state = (session.last_gateway_state or {}) if session else {}
        checked_at = session.last_checked_at if session else None
        age = _age_seconds(checked_at, now)
        connected = bool(
            session
            and session.status == BrokerGatewaySession.Status.CONNECTED
            and session.commands_enabled
            and state.get("connected") is True
            and age is not None
            and age <= gateway_stale_seconds
        )
        reconciled = bool(connected and state.get("reconciled") is True)
        row = {
            "session_id": str(session_id),
            "portfolio_ids": sorted(scoped_portfolios),
            "status": session.status if session else "MISSING",
            "commands_enabled": bool(session and session.commands_enabled),
            "connected": connected,
            "reconciled": reconciled,
            "last_checked_at": checked_at,
            "age_seconds": age,
            "stale_after_seconds": gateway_stale_seconds,
        }
        session_rows.append(row)
        if not connected:
            bad_connectivity.append(str(session_id))
        elif not reconciled:
            bad_gateway_reconciliation.append(str(session_id))

    blockers = []
    if missing_session_portfolios or bad_connectivity:
        blockers.append(
            {
                "code": "GATEWAY_NOT_CONNECTED",
                "message": "A PAPER portfolio has no healthy connected Gateway",
                "details": {
                    "missing_session_portfolio_ids": sorted(
                        set(missing_session_portfolios)
                    ),
                    "session_ids": bad_connectivity,
                },
            }
        )
    if bad_gateway_reconciliation:
        blockers.append(
            {
                "code": "GATEWAY_NOT_RECONCILED",
                "message": "A required Gateway session is not broker-reconciled",
                "details": {"session_ids": bad_gateway_reconciliation},
            }
        )

    breaks = ReconciliationBreak.objects.filter(
        material=True,
        resolved=False,
        run__broker_account_id__in=scope["account_ids"],
    )
    bad_break_account_ids = set(
        breaks.values_list("run__broker_account_id", flat=True)
    )
    accounts = {
        item.pk: item
        for item in BrokerAccount.objects.filter(pk__in=scope["account_ids"])
    }
    account_rows = []
    unreconciled_accounts = []
    for account_id in scope["account_ids"]:
        account = accounts.get(account_id)
        reconciled = bool(
            account
            and account.is_reconciled
            and account_id not in bad_break_account_ids
        )
        account_rows.append(
            {
                "account_id": account_id,
                "broker_account_id": account.account_id if account else None,
                "reconciled": reconciled,
                "material_breaks": breaks.filter(
                    run__broker_account_id=account_id
                ).count(),
            }
        )
        if not reconciled:
            unreconciled_accounts.append(account_id)
    if unreconciled_accounts:
        blockers.append(
            {
                "code": "BROKER_RECONCILIATION_NOT_READY",
                "message": "A PAPER portfolio account is not reconciled",
                "details": {"account_ids": unreconciled_accounts},
            }
        )

    gateway_signal = {
        "status": "HEALTHY"
        if not (missing_session_portfolios or bad_connectivity)
        else "DEGRADED",
        "required_session_count": len(portfolios_by_session),
        "sessions": session_rows,
    }
    reconciliation_signal = {
        "status": "HEALTHY"
        if not (bad_gateway_reconciliation or unreconciled_accounts)
        else "DEGRADED",
        "account_count": len(scope["account_ids"]),
        "accounts": account_rows,
        "unresolved_material_breaks": breaks.count(),
        "portfolio_ids": portfolio_ids,
    }
    return gateway_signal, reconciliation_signal, blockers


def collect_execution_readiness(*, http_get=None, now=None):
    now = now or timezone.now()
    http_get = http_get or requests.get
    blockers = []

    required_jobs = _setting_tuple(
        "EXECUTION_REQUIRED_FLINK_JOBS", DEFAULT_REQUIRED_FLINK_JOBS
    )
    flink_signal, flink_blockers = _flink_readiness(
        http_get=http_get,
        required_jobs=required_jobs,
        checkpoint_stale_seconds=int(
            getattr(settings, "FLINK_CHECKPOINT_STALE_SECONDS", 180)
        ),
        request_timeout_seconds=float(
            getattr(settings, "EXECUTION_READINESS_HTTP_TIMEOUT_SECONDS", 2)
        ),
        now=now,
    )
    blockers.extend(flink_blockers)

    if not settings.KAFKA_ENABLED:
        blockers.append(
            {
                "code": "KAFKA_DISABLED",
                "message": "Kafka is disabled",
                "details": {},
            }
        )

    raw_metric = StreamHealthMetric.objects.filter(
        component="market-raw-producer", metric="heartbeat"
    ).first()
    raw_signal = _heartbeat_signal(
        raw_metric,
        stale_seconds=int(
            getattr(
                settings,
                "MARKET_RAW_PRODUCER_HEARTBEAT_STALE_SECONDS",
                30,
            )
        ),
        now=now,
    )
    if not raw_signal["healthy"]:
        blockers.append(
            {
                "code": "MARKET_RAW_PRODUCER_HEARTBEAT_STALE",
                "message": "The market raw producer heartbeat is missing or stale",
                "details": {"age_seconds": raw_signal["age_seconds"]},
            }
        )

    consumer_metric = StreamHealthMetric.objects.filter(
        component="backend-market-consumer", metric="heartbeat"
    ).first()
    consumer_signal = _heartbeat_signal(
        consumer_metric,
        stale_seconds=int(settings.MARKET_CONSUMER_HEARTBEAT_STALE_SECONDS),
        now=now,
    )
    if not consumer_signal["healthy"]:
        blockers.append(
            {
                "code": "MARKET_CONSUMER_HEARTBEAT_STALE",
                "message": "The Backend market consumer heartbeat is missing or stale",
                "details": {"age_seconds": consumer_signal["age_seconds"]},
            }
        )

    worker_stale_seconds = int(
        getattr(settings, "EXECUTION_WORKER_HEARTBEAT_STALE_SECONDS", 30)
    )
    worker_metrics = {
        item.metric: item
        for item in StreamHealthMetric.objects.filter(
            component="execution-worker", metric__in=REQUIRED_WORKER_ROLES
        )
    }
    worker_signals = {}
    missing_workers = []
    for role in REQUIRED_WORKER_ROLES:
        worker_signals[role] = _heartbeat_signal(
            worker_metrics.get(role),
            stale_seconds=worker_stale_seconds,
            now=now,
        )
        if not worker_signals[role]["healthy"]:
            missing_workers.append(role)
    if missing_workers:
        blockers.append(
            {
                "code": "EXECUTION_WORKERS_ABSENT",
                "message": "One or more required execution workers are absent or stale",
                "details": {"roles": missing_workers},
            }
        )

    scope = _paper_scope(now)
    if scope["stale_strategies"]:
        blockers.append(
            {
                "code": "MARKET_DATA_STALE",
                "message": "Market data is stale or incomplete for a PAPER strategy",
                "details": {"strategies": scope["stale_strategies"]},
            }
        )

    strategy_jobs = StrategyEvaluationJob.objects.filter(
        status__in=ACTIVE_STRATEGY_JOB_STATUSES
    )
    strategy_oldest, strategy_age = _oldest_age(strategy_jobs, "created_at", now)
    strategy_threshold = int(
        getattr(settings, "STRATEGY_JOB_BACKLOG_THRESHOLD", 100)
    )
    strategy_backlog = strategy_jobs.count()
    strategy_signal = {
        "status": "HEALTHY"
        if strategy_backlog <= strategy_threshold
        else "DEGRADED",
        "count": strategy_backlog,
        "runnable_count": strategy_jobs.filter(
            status__in=["PENDING", "RETRY"], next_attempt_at__lte=now
        ).count(),
        "waiting_for_input_count": strategy_jobs.filter(
            status="WAITING_FOR_INPUT"
        ).count(),
        "oldest_created_at": strategy_oldest,
        "oldest_age_seconds": strategy_age,
        "threshold": strategy_threshold,
    }
    if strategy_backlog > strategy_threshold:
        blockers.append(
            {
                "code": "STRATEGY_JOB_BACKLOG_EXCEEDED",
                "message": "Strategy evaluation backlog exceeds its threshold",
                "details": {
                    "count": strategy_backlog,
                    "threshold": strategy_threshold,
                },
            }
        )

    coordination = PortfolioTargetCoordination.objects.filter(
        Q(needs_coordination=True) | Q(pending_recalculation=True)
    )
    coordination_oldest, coordination_age = _oldest_age(
        coordination.exclude(requested_at__isnull=True), "requested_at", now
    )
    coordination_threshold = int(
        getattr(settings, "TARGET_COORDINATION_BACKLOG_THRESHOLD", 100)
    )
    coordination_count = coordination.count()
    coordination_signal = {
        "status": "HEALTHY"
        if coordination_count <= coordination_threshold
        else "DEGRADED",
        "count": coordination_count,
        "pending_recalculation_count": coordination.filter(
            pending_recalculation=True
        ).count(),
        "oldest_requested_at": coordination_oldest,
        "oldest_age_seconds": coordination_age,
        "threshold": coordination_threshold,
    }
    if coordination_count > coordination_threshold:
        blockers.append(
            {
                "code": "TARGET_COORDINATION_BACKLOG_EXCEEDED",
                "message": "Target coordination backlog exceeds its threshold",
                "details": {
                    "count": coordination_count,
                    "threshold": coordination_threshold,
                },
            }
        )

    active_rebalances = RebalanceRun.objects.filter(
        automatic=True, status__in=ACTIVE_REBALANCE_STATUSES
    )
    rebalance_oldest, rebalance_age = _oldest_age(
        active_rebalances, "created_at", now
    )
    rebalance_signal = {
        "status": "HEALTHY",
        "count": active_rebalances.count(),
        "portfolio_count": active_rebalances.values("portfolio_id").distinct().count(),
        "oldest_created_at": rebalance_oldest,
        "oldest_age_seconds": rebalance_age,
    }

    pending_intents = OrderIntent.objects.filter(
        mode="PAPER",
        eligible=True,
        operation_status__in=PENDING_INTENT_STATUSES,
    )
    intent_oldest, intent_age = _oldest_age(pending_intents, "created_at", now)
    intent_max_age = int(getattr(settings, "PENDING_INTENT_MAX_AGE_SECONDS", 60))
    intent_signal = {
        "status": "DEGRADED"
        if intent_age is not None and intent_age > intent_max_age
        else "HEALTHY",
        "count": pending_intents.count(),
        "oldest_created_at": intent_oldest,
        "oldest_age_seconds": intent_age,
        "maximum_age_seconds": intent_max_age,
    }
    if intent_signal["status"] == "DEGRADED":
        blockers.append(
            {
                "code": "PENDING_INTENT_STALE",
                "message": "A pending PAPER intent exceeds its maximum age",
                "details": {"oldest_age_seconds": intent_age},
            }
        )

    pending_commands = BrokerCommand.objects.filter(
        status__in=PENDING_BROKER_COMMAND_STATUSES
    )
    command_oldest, command_age = _oldest_age(
        pending_commands, "created_at", now
    )
    command_max_age = int(getattr(settings, "BROKER_COMMAND_MAX_AGE_SECONDS", 60))
    uncertain = BrokerCommand.objects.filter(status=BrokerCommand.Status.UNCERTAIN)
    scoped_uncertain = uncertain.filter(order__intent__mode="PAPER")
    command_signal = {
        "status": "DEGRADED"
        if command_age is not None and command_age > command_max_age
        else "HEALTHY",
        "count": pending_commands.count(),
        "oldest_created_at": command_oldest,
        "oldest_age_seconds": command_age,
        "maximum_age_seconds": command_max_age,
        "uncertain_count": uncertain.count(),
        "scoped_uncertain_count": scoped_uncertain.count(),
        "uncertain_portfolio_ids": sorted(
            set(
                scoped_uncertain.values_list(
                    "order__intent__portfolio_id", flat=True
                )
            )
        ),
    }
    if command_signal["status"] == "DEGRADED":
        blockers.append(
            {
                "code": "BROKER_COMMAND_STALE",
                "message": "A broker command exceeds its maximum pending age",
                "details": {"oldest_age_seconds": command_age},
            }
        )
    if command_signal["scoped_uncertain_count"]:
        blockers.append(
            {
                "code": "UNRESOLVED_UNCERTAIN_ORDER",
                "message": "An uncertain broker order blocks a PAPER portfolio",
                "details": {
                    "portfolio_ids": command_signal["uncertain_portfolio_ids"],
                    "count": command_signal["scoped_uncertain_count"],
                },
            }
        )

    gateway_signal, reconciliation_signal, gateway_blockers = (
        _gateway_and_reconciliation(scope, now)
    )
    blockers.extend(gateway_blockers)

    ready = not blockers
    return {
        "ready": ready,
        "automatic_execution_ready": ready,
        "status": "READY" if ready else "NOT_READY",
        "execution_mode": settings.NEW_EXECUTION_MODE,
        "observed_at": now,
        "blockers": blockers,
        "signals": {
            "market_raw_producer": raw_signal,
            "flink": flink_signal,
            "kafka_consumer": consumer_signal,
            "workers": worker_signals,
            "paper_scope": {
                "strategy_count": scope["strategy_count"],
                "portfolio_ids": scope["portfolio_ids"],
                "instrument_ids": scope["instrument_ids"],
                "stale_strategies": scope["stale_strategies"],
            },
            "strategy_job_backlog": strategy_signal,
            "target_coordination_backlog": coordination_signal,
            "active_rebalances": rebalance_signal,
            "pending_intents": intent_signal,
            "broker_commands": command_signal,
            "gateway": gateway_signal,
            "broker_reconciliation": reconciliation_signal,
        },
    }
