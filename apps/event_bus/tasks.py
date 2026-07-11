from celery import shared_task
from django.conf import settings
from django.utils import timezone
from .models import StreamHealthMetric
from .services import publish_batch


@shared_task
def publish_outbox_events():
    return publish_batch()


@shared_task
def check_stream_health():
    status, value = "DISABLED", {"enabled": False}
    if settings.KAFKA_ENABLED:
        try:
            from confluent_kafka.admin import AdminClient
            metadata = AdminClient({"bootstrap.servers": settings.KAFKA_BOOTSTRAP_SERVERS}).list_topics(timeout=5)
            status, value = "HEALTHY", {"enabled": True, "topics": len(metadata.topics)}
        except Exception as exc:
            status, value = "DEGRADED", {"enabled": True, "error": str(exc)[:255]}
    metric, _ = StreamHealthMetric.objects.update_or_create(component="kafka", metric="connectivity",
                                                              defaults={"status": status, "value": value})
    return {"status": metric.status, "observed_at": timezone.now().isoformat()}


@shared_task
def execute_replay_request(request_id):
    from .services import execute_replay
    return execute_replay(request_id)
