from celery import shared_task

from datetime import timedelta
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .configuration import (
    ManagedBrokerGatewayUnavailable,
    managed_broker_deployment_configuration,
    managed_broker_disabled_task_result,
)
from .models import BrokerGatewaySession, BrokerGatewaySessionSecret
from .qch import QCHError
from .services import inspect_gateway_session, provision_session, record_provision_failure


@shared_task(bind=True, max_retries=2, default_retry_delay=5)
def provision_broker_session(self, session_id):
    try:
        return provision_session(session_id)
    except ManagedBrokerGatewayUnavailable as exc:
        return managed_broker_disabled_task_result(exc.configuration)
    except QCHError as exc:
        if exc.retryable and self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return record_provision_failure(session_id, exc, final=True)


@shared_task
def monitor_broker_sessions():
    deployment = managed_broker_deployment_configuration()
    if not deployment["available"]:
        return managed_broker_disabled_task_result(deployment)

    now = timezone.now()
    expired_session_ids = list(BrokerGatewaySessionSecret.objects.filter(
        expires_at__lte=now
    ).values_list("session_id", flat=True))
    BrokerGatewaySessionSecret.objects.filter(session_id__in=expired_session_ids).delete()
    BrokerGatewaySession.objects.filter(
        pk__in=expired_session_ids,
        status=BrokerGatewaySession.Status.CREATING,
    ).update(
        status=BrokerGatewaySession.Status.LOGIN_FAILED,
        commands_enabled=False,
        last_error="Temporary IBKR credentials expired before provisioning",
        last_checked_at=now,
    )

    stale_before = now - timedelta(seconds=int(settings.BROKER_SESSION_CREATING_STALE_SECONDS))
    stale_creating = BrokerGatewaySession.objects.filter(
        status=BrokerGatewaySession.Status.CREATING,
        deleted_at__isnull=True,
    ).filter(Q(last_checked_at__lt=stale_before) | Q(last_checked_at__isnull=True, updated_at__lt=stale_before))
    recovered = []
    for session_id in stale_creating.values_list("pk", flat=True):
        updated = BrokerGatewaySession.objects.filter(
            pk=session_id,
            status=BrokerGatewaySession.Status.CREATING,
        ).update(last_checked_at=now, last_error="Recovering stale broker-session provisioning")
        if updated:
            provision_broker_session.delay(str(session_id))
            recovered.append(str(session_id))

    results = {}
    for session in BrokerGatewaySession.objects.exclude(
        status__in=[
            BrokerGatewaySession.Status.CREATING,
            BrokerGatewaySession.Status.LOGIN_FAILED,
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
    if recovered:
        results["recovered_creating"] = recovered
    return results


@shared_task
def sync_broker_events():
    # Kept as the established task name; monitoring now owns independent per-session sync.
    return monitor_broker_sessions()
