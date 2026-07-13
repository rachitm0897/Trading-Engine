from celery import shared_task
from .models import BrokerContract
from .services import publish_instrument_registry


@shared_task
def publish_instrument_registry_snapshot():
    count=0
    for contract in BrokerContract.objects.select_related("instrument"):
        publish_instrument_registry(contract);count+=1
    return count
