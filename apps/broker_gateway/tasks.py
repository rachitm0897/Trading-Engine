from celery import shared_task
from .sync import sync_events

@shared_task
def sync_broker_events():
    return sync_events()

