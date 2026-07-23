from celery import shared_task

from .dispatch import (
    process_broker_commands,
    process_order_intents,
    recover_stuck_broker_commands,
)


@shared_task
def execute_order_intents(limit=None):
    return process_order_intents(limit=limit)


@shared_task
def dispatch_broker_commands(limit=None):
    return process_broker_commands(limit=limit)


@shared_task
def recover_broker_commands():
    return recover_stuck_broker_commands()
