from celery import shared_task
from .services import recover_incomplete


@shared_task
def recover_incomplete_rebalances():
    return recover_incomplete()
