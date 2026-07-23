from celery import shared_task

from .evaluation_jobs import (
    process_strategy_evaluation_jobs,
    recover_stuck_strategy_evaluation_jobs,
)


@shared_task
def execute_strategy_evaluation_jobs(limit=None):
    return process_strategy_evaluation_jobs(limit=limit)


@shared_task
def recover_strategy_evaluation_jobs():
    return recover_stuck_strategy_evaluation_jobs()
