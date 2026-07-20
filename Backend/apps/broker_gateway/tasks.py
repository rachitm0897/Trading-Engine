from celery import shared_task

from django.utils import timezone

from .models import BrokerGatewaySession, BrokerGatewaySessionSecret
from .services import inspect_gateway_session, provision_session


@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def provision_broker_session(self, session_id):
    status = provision_session(session_id)
    if status == BrokerGatewaySession.Status.ERROR:
        session = BrokerGatewaySession.objects.get(pk=session_id)
        if session.last_error and "credentials" not in session.last_error.lower():
            raise self.retry(exc=RuntimeError(session.last_error))
    return status


@shared_task
def monitor_broker_sessions():
    BrokerGatewaySessionSecret.objects.filter(expires_at__lte=timezone.now()).delete()
    results = {}
    for session in BrokerGatewaySession.objects.exclude(
        status__in=[
            BrokerGatewaySession.Status.CREATING,
            BrokerGatewaySession.Status.STOPPING,
            BrokerGatewaySession.Status.DELETED,
        ]
    ).order_by("created_at"):
        try:
            results[str(session.pk)] = inspect_gateway_session(session).status
        except Exception as exc:
            BrokerGatewaySession.objects.filter(pk=session.pk).update(
                status=BrokerGatewaySession.Status.ERROR,
                commands_enabled=False,
                last_error=str(exc)[:4000],
            )
            results[str(session.pk)] = BrokerGatewaySession.Status.ERROR
    return results


@shared_task
def sync_broker_events():
    # Kept as the established task name; monitoring now owns independent per-session sync.
    return monitor_broker_sessions()
