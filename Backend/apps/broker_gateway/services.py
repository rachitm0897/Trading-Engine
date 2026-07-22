import re
import secrets
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import BrokerAccount
from apps.portfolios.models import TradingPortfolio

from .client import GatewayClient, GatewayError
from .configuration import configured_gateway_image, require_managed_broker_deployment
from .crypto import decrypt_secret
from .models import (
    BrokerGatewaySession,
    BrokerGatewaySessionSecret,
    BrokerSessionAccount,
)
from .qch import QCHBrokerClient, QCHError


CONTAINER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
RUNNING_CONTAINER_STATES = {"RUNNING", "STARTED", "UP", "HEALTHY"}
EXITED_CONTAINER_STATES = {"EXITED", "DEAD", "FAILED", "STOPPED", "REMOVED"}


def container_name_for(session_id):
    return f"trading-engine-ibkr-{str(session_id).replace('-', '')[:20]}"


def temporary_secret_expiry():
    return timezone.now() + timedelta(seconds=int(settings.BROKER_CREDENTIAL_TTL_SECONDS))


def gateway_environment(session, username, password, gateway_token, novnc_password):
    return {
        # This secret exists only in the QCH create request and the child
        # process environment. It is intentionally not stored on the session.
        "DJANGO_SECRET_KEY": secrets.token_urlsafe(64),
        "IB_USERNAME": username,
        "IB_PASSWORD": password,
        "IBC_TRADING_MODE": session.mode,
        "GATEWAY_SERVICE_TOKEN": gateway_token,
        "NOVNC_PASSWORD": novnc_password,
        "BROKER_ADAPTER": "ib_async",
        "PORT": "8080",
        "APP_BASE_PATH": "",
    }


def _container_state(container):
    return {"id": container.id, "name": container.name, "status": container.status}


def _safe_provision_error(exc):
    if isinstance(exc, QCHError):
        return str(exc)[:4000]
    if isinstance(exc, ValueError):
        return str(exc)[:4000]
    return "Broker session provisioning failed"


def record_provision_failure(session_id, exc, *, final):
    """Record a provisioning failure without ever copying request secrets."""
    with transaction.atomic():
        session = BrokerGatewaySession.objects.select_for_update().get(pk=session_id)
        if session.status not in {session.Status.STOPPING, session.Status.DELETED}:
            retryable = isinstance(exc, QCHError) and exc.retryable and not final
            if retryable:
                session.status = session.Status.STARTING if session.provisioned_at else session.Status.CREATING
            else:
                session.status = session.Status.LOGIN_FAILED if isinstance(exc, ValueError) else session.Status.ERROR
            session.commands_enabled = False
            session.last_error = _safe_provision_error(exc)
            session.last_checked_at = timezone.now()
            session.lifecycle_version += 1
            session.save(update_fields=[
                "status", "commands_enabled", "last_error", "last_checked_at", "lifecycle_version", "updated_at"
            ])
    if final or not (isinstance(exc, QCHError) and exc.retryable):
        BrokerGatewaySessionSecret.objects.filter(session_id=session_id).delete()
    return session.status


def _adopt_container(session_id, container):
    with transaction.atomic():
        session = BrokerGatewaySession.objects.select_for_update().get(pk=session_id)
        if session.status in {session.Status.STOPPING, session.Status.DELETED}:
            return session
        if container.name != session.child_container_name:
            raise QCHError("QCH returned a child container with an unexpected name")
        session.child_container_id = container.id or session.child_container_id or container.name
        session.internal_base_url = f"http://{session.child_container_name}:8080/api/v1"
        session.last_qch_state = _container_state(container)
        session.status = session.Status.STARTING
        session.last_error = ""
        session.provisioned_at = session.provisioned_at or timezone.now()
        session.lifecycle_version += 1
        session.save(update_fields=[
            "child_container_id", "internal_base_url", "last_qch_state", "status", "last_error",
            "provisioned_at", "lifecycle_version", "updated_at",
        ])
        return session


def synchronize_accounts(session, client, account_rows=None, summary_rows=None):
    account_rows = client.accounts() if account_rows is None else account_rows
    summary_rows = client.account_summary() if summary_rows is None else summary_rows
    summaries = {}
    for row in summary_rows or []:
        account_id = str(row.get("account") or row.get("account_id") or "")
        if account_id and row.get("tag"):
            summaries.setdefault(account_id, {})[str(row["tag"])] = row
    seen = set()
    with transaction.atomic():
        BrokerGatewaySession.objects.select_for_update().get(pk=session.pk)
        for row in account_rows or []:
            account_id = str(row if isinstance(row, str) else row.get("account_id") or row.get("account") or "").strip()
            if not account_id:
                continue
            seen.add(account_id)
            alias = "" if isinstance(row, str) else str(row.get("alias") or "")[:128]
            account, _ = BrokerAccount.objects.get_or_create(
                account_id=account_id, defaults={"alias": alias or f"IBKR {account_id}"}
            )
            if alias and account.alias != alias:
                account.alias = alias
                account.save(update_fields=["alias", "updated_at"])
            BrokerSessionAccount.objects.update_or_create(
                session=session,
                broker_account=account,
                defaults={"broker_alias": alias, "available": True},
            )
            if not TradingPortfolio.objects.filter(account=account, gateway_session=session).exists():
                TradingPortfolio.objects.create(
                    account=account, gateway_session=session, name=f"{session.display_name} · {account_id}"[:128]
                )
        BrokerSessionAccount.objects.filter(session=session).exclude(
            broker_account__account_id__in=seen
        ).update(available=False)
    # Reuse the broker projection logic without ever exposing a global route.
    from .sync import sync_account_summary
    sync_account_summary(summary_rows or [], gateway_session=session)
    return len(seen)


def inspect_gateway_session(session, *, qch_client=None, container=None, synchronize=True):
    require_managed_broker_deployment()
    qch = qch_client or QCHBrokerClient()
    if container is None:
        container = qch.find_by_name(session.child_container_name)
    if container is None:
        with transaction.atomic():
            locked = BrokerGatewaySession.objects.select_for_update().get(pk=session.pk)
            if locked.status not in {locked.Status.STOPPING, locked.Status.DELETED}:
                locked.mark_checked(status=locked.Status.ERROR, error="QCH child container is missing")
                locked.commands_enabled = False
                locked.lifecycle_version += 1
                locked.save(update_fields=[
                    "status", "commands_enabled", "last_error", "last_checked_at", "lifecycle_version", "updated_at"
                ])
            return locked
    if container.status in EXITED_CONTAINER_STATES:
        with transaction.atomic():
            locked = BrokerGatewaySession.objects.select_for_update().get(pk=session.pk)
            locked.mark_checked(
                status=locked.Status.DISCONNECTED,
                qch_state=_container_state(container),
                error=f"QCH child container is {container.status.lower()} and does not auto-restart",
            )
            locked.commands_enabled = False
            locked.lifecycle_version += 1
            locked.save(update_fields=[
                "status", "commands_enabled", "last_qch_state", "last_error", "last_checked_at",
                "lifecycle_version", "updated_at",
            ])
            return locked
    try:
        public_health = requests.get(
            f"http://{session.child_container_name}:8080/healthz",
            timeout=float(settings.BROKER_SESSION_HEALTH_TIMEOUT_SECONDS),
        )
        public_health.raise_for_status()
    except requests.RequestException:
        with transaction.atomic():
            locked = BrokerGatewaySession.objects.select_for_update().get(pk=session.pk)
            locked.mark_checked(status=locked.Status.STARTING, qch_state=_container_state(container))
            locked.commands_enabled = False
            locked.save(update_fields=[
                "status", "commands_enabled", "last_qch_state", "last_error", "last_checked_at", "updated_at"
            ])
            return locked
    try:
        client = GatewayClient(session)
        state = client.health() or {}
        connected = bool(state.get("connected"))
        status = session.Status.CONNECTED if connected else (
            session.Status.WAITING_FOR_2FA if session.mode == session.Mode.LIVE else session.Status.WAITING_FOR_LOGIN
        )
        if synchronize and connected:
            synchronize_accounts(session, client)
            from .sync import sync_events
            sync_events(client, gateway_session=session)
        with transaction.atomic():
            locked = BrokerGatewaySession.objects.select_for_update().get(pk=session.pk)
            locked.mark_checked(status=status, gateway_state=state, qch_state=_container_state(container))
            locked.commands_enabled = connected
            if connected:
                locked.connected_at = locked.connected_at or timezone.now()
            locked.lifecycle_version += 1
            fields = [
                "status", "last_gateway_state", "last_qch_state", "last_error", "last_checked_at",
                "commands_enabled", "lifecycle_version", "updated_at",
            ]
            if connected:
                fields.append("connected_at")
            locked.save(update_fields=fields)
            return locked
    except GatewayError as exc:
        with transaction.atomic():
            locked = BrokerGatewaySession.objects.select_for_update().get(pk=session.pk)
            status = locked.Status.WAITING_FOR_2FA if locked.mode == locked.Mode.LIVE else locked.Status.WAITING_FOR_LOGIN
            locked.mark_checked(status=status, qch_state=_container_state(container), error=str(exc))
            locked.commands_enabled = False
            locked.save(update_fields=[
                "status", "commands_enabled", "last_qch_state", "last_error", "last_checked_at", "updated_at"
            ])
            return locked


def provision_session(session_id, *, qch_client=None, sleep=time.sleep):
    require_managed_broker_deployment()
    try:
        configured_image = configured_gateway_image()
        qch = qch_client or QCHBrokerClient()
        session = BrokerGatewaySession.objects.get(pk=session_id)
        if session.status in {session.Status.STOPPING, session.Status.DELETED}:
            return session.status
        secret = BrokerGatewaySessionSecret.objects.filter(session=session).first()
        existing = qch.find_by_name(session.child_container_name)
        if (
            existing is not None
            and secret is not None
            and session.status == session.Status.CREATING
            and session.child_container_id
            and existing.id == session.child_container_id
        ):
            raise QCHError("Previous QCH child deletion is still in progress", retryable=True)
        if existing is None:
            if secret is None:
                raise ValueError("IBKR credentials expired or were consumed; re-enter credentials to provision again")
            if secret.expires_at <= timezone.now():
                raise ValueError("Temporary IBKR credentials expired before provisioning")
            username = decrypt_secret(secret.encrypted_username)
            password = decrypt_secret(secret.encrypted_password)
            gateway_token = decrypt_secret(session.encrypted_gateway_token)
            novnc_password = decrypt_secret(session.encrypted_novnc_password)
            try:
                existing = qch.create_container(
                    name=session.child_container_name,
                    image=configured_image,
                    env=gateway_environment(session, username, password, gateway_token, novnc_password),
                    network=settings.QCH_SUBCONTAINER_NETWORK,
                )
            except QCHError as exc:
                # A timed-out create can still have succeeded. Resolve the
                # expected immutable name before any retry can create again.
                if not exc.retryable:
                    raise
                existing = qch.find_by_name(session.child_container_name)
                if existing is None:
                    raise exc
        session = _adopt_container(session_id, existing)
        # Credentials are single-use only after QCH has created or confirmed
        # ownership of the expected child name.
        BrokerGatewaySessionSecret.objects.filter(session_id=session_id).delete()
        deadline = time.monotonic() + max(0, float(settings.BROKER_SESSION_START_TIMEOUT_SECONDS))
        while True:
            session = inspect_gateway_session(session, qch_client=qch, container=existing, synchronize=False)
            if session.status not in {session.Status.STARTING} or time.monotonic() >= deadline:
                return session.status
            sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    except QCHError as exc:
        record_provision_failure(session_id, exc, final=not exc.retryable)
        if exc.retryable:
            raise
        return BrokerGatewaySession.Status.ERROR
    except Exception as exc:
        return record_provision_failure(session_id, exc, final=True)


def delete_session(session_id, *, qch_client=None):
    require_managed_broker_deployment()
    with transaction.atomic():
        session = BrokerGatewaySession.objects.select_for_update().get(pk=session_id)
        if session.status == session.Status.DELETED:
            return session, False
        session.status = session.Status.STOPPING
        session.commands_enabled = False
        session.lifecycle_version += 1
        session.save(update_fields=["status", "commands_enabled", "lifecycle_version", "updated_at"])
        session.portfolios.update(kill_switch=True)
        from apps.strategies.models import StrategyInstance
        StrategyInstance.objects.filter(portfolio__gateway_session=session, enabled=True).update(
            enabled=False, state="PAUSED", block_reason="Broker gateway session was deleted"
        )
        session.market_subscriptions.update(
            state="INACTIVE", consumer_count=0, active_provider="NONE", last_error="Broker gateway session was deleted"
        )
        BrokerAccount.objects.filter(gateway_sessions__session=session).update(is_reconciled=False)
    if session.child_container_name:
        qch = qch_client or QCHBrokerClient()
        try:
            qch.delete_container(session.child_container_name)
        except QCHError as exc:
            with transaction.atomic():
                locked = BrokerGatewaySession.objects.select_for_update().get(pk=session_id)
                locked.status = locked.Status.ERROR
                locked.last_error = str(exc)[:4000]
                locked.last_checked_at = timezone.now()
                locked.save(update_fields=["status", "last_error", "last_checked_at", "updated_at"])
            raise
    with transaction.atomic():
        session = BrokerGatewaySession.objects.select_for_update().get(pk=session_id)
        session.status = session.Status.DELETED
        session.commands_enabled = False
        session.deleted_at = session.deleted_at or timezone.now()
        session.last_checked_at = timezone.now()
        session.last_error = ""
        session.lifecycle_version += 1
        session.save(update_fields=[
            "status", "commands_enabled", "deleted_at", "last_checked_at", "last_error",
            "lifecycle_version", "updated_at",
        ])
        BrokerGatewaySessionSecret.objects.filter(session=session).delete()
        BrokerSessionAccount.objects.filter(session=session).update(available=False)
    return session, True
