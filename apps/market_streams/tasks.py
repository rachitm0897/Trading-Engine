from celery import shared_task
from .subscriptions import restore_market_subscriptions


@shared_task
def restore_active_market_subscriptions():return restore_market_subscriptions()
