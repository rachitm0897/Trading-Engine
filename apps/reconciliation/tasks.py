from celery import shared_task
from .services import reconcile

@shared_task
def run_scheduled_reconciliation():
    return reconcile("scheduled").pk
