from celery import shared_task
from django.utils import timezone
from .models import OutboxEvent

@shared_task
def dispatch_outbox():
    count = 0
    for event in OutboxEvent.objects.filter(published_at__isnull=True).order_by("id")[:100]:
        event.attempts += 1; event.published_at = timezone.now(); event.save(update_fields=["attempts", "published_at"]); count += 1
    return count

