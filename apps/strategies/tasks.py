import socket

from celery import shared_task

from apps.execution.readiness import record_worker_heartbeat

from .evaluation_jobs import (
    process_strategy_evaluation_jobs,
    recover_stuck_strategy_evaluation_jobs,
)


def _run_with_heartbeat(callback):
    role = "strategy_evaluation"
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
def execute_strategy_evaluation_jobs(limit=None):
    return _run_with_heartbeat(
        lambda: process_strategy_evaluation_jobs(limit=limit)
    )


@shared_task
def recover_strategy_evaluation_jobs():
    return _run_with_heartbeat(recover_stuck_strategy_evaluation_jobs)
