from celery import shared_task
from apps.accounts.models import BrokerAccount
from .services import reconcile

@shared_task
def run_scheduled_reconciliation():
    return [
        reconcile("scheduled", broker_account_id=account_id).pk
        for account_id in BrokerAccount.objects.values_list("account_id", flat=True)
    ]
