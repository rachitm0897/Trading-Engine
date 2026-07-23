import socket

from celery import shared_task

from .readiness import record_worker_heartbeat
from .dispatch import (
    process_broker_commands,
    process_order_intents,
    recover_stuck_broker_commands,
    recover_stuck_order_intents,
)


def _run_with_heartbeat(role, callback):
    worker = socket.gethostname()
    record_worker_heartbeat(role, status="RUNNING", worker=worker)
    try:
        result = callback()
    except Exception as exc:
        record_worker_heartbeat(
            role,
            status="DEGRADED",
            worker=worker,
            details={"error": str(exc)[:255]},
        )
        raise
    record_worker_heartbeat(
        role,
        worker=worker,
        details={"last_result": result},
    )
    return result


@shared_task
def execute_order_intents(limit=None):
    return _run_with_heartbeat(
        "intent_execution",
        lambda: process_order_intents(limit=limit),
    )


@shared_task
def dispatch_broker_commands(limit=None):
    return _run_with_heartbeat(
        "broker_commands",
        lambda: process_broker_commands(limit=limit),
    )


@shared_task
def recover_broker_commands():
    return _run_with_heartbeat(
        "broker_commands",
        recover_stuck_broker_commands,
    )


@shared_task
def recover_order_intents():
    return _run_with_heartbeat(
        "intent_execution",
        recover_stuck_order_intents,
    )
