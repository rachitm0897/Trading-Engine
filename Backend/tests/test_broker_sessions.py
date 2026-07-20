import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
import responses
from django.test import RequestFactory, override_settings
from django.utils import timezone

from apps.accounts.models import BrokerAccount
from apps.broker_gateway.client import GatewayClient, GatewayRoute, GatewayRouteError, GatewaySessionUnavailable
from apps.broker_gateway.crypto import decrypt_secret, encrypt_secret, issue_novnc_access_token
from apps.broker_gateway.models import (
    BrokerGatewaySession,
    BrokerGatewaySessionSecret,
    BrokerSessionAccount,
    BrokerSyncCursor,
)
from apps.broker_gateway.qch import QCHBrokerClient, QCHConflict, QCHContainer, QCHError
from apps.broker_gateway.services import (
    delete_session,
    inspect_gateway_session,
    provision_session,
    record_provision_failure,
    synchronize_accounts,
)
from apps.broker_gateway.tasks import monitor_broker_sessions
from apps.portfolios.models import TradingPortfolio


pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def broker_settings(settings, monkeypatch):
    settings.BROKER_SESSION_ENCRYPTION_KEY = "broker-session-unit-test-key"
    settings.BROKER_CREDENTIAL_TTL_SECONDS = 900
    settings.BROKER_SESSION_CREATING_STALE_SECONDS = 60
    settings.BROKER_SESSION_START_TIMEOUT_SECONDS = 0
    settings.BROKER_SESSION_HEALTH_TIMEOUT_SECONDS = 1
    settings.NOVNC_ACCESS_TOKEN_TTL_SECONDS = 300
    settings.NOVNC_PROXY_CONNECT_TIMEOUT_SECONDS = 1
    settings.NOVNC_PROXY_MAX_BODY_BYTES = 1024 * 1024
    settings.IBKR_GATEWAY_IMAGE = "registry.example/ibkr@sha256:abc"
    settings.QCH_SUBCONTAINER_NETWORK = "traefik"
    settings.QCH_API_HOST = "https://qch.example"
    settings.QCH_APP_ID = "app-1"
    settings.QCH_SERVICE_TOKEN = "qch-secret"
    settings.QCH_REQUEST_TIMEOUT_SECONDS = 3
    monkeypatch.setenv("QCH_API_HOST", "https://qch.example")
    monkeypatch.setenv("QCH_APP_ID", "app-1")
    monkeypatch.setenv("QCH_SERVICE_TOKEN", "qch-secret")


def make_session(name="Paper one", mode="paper", *, status="CREATING"):
    session = BrokerGatewaySession(
        display_name=name,
        username_hint="du••er",
        mode=mode,
        status=status,
        commands_enabled=status == "CONNECTED",
        child_container_name="pending",
        encrypted_gateway_token=encrypt_secret(f"token-{name}"),
        encrypted_novnc_password=encrypt_secret("vnc-pass"),
    )
    session.child_container_name = f"trading-engine-ibkr-{str(session.pk).replace('-', '')[:20]}"
    session.internal_base_url = f"http://{session.child_container_name}:8080/api/v1"
    if status == "CONNECTED":
        session.last_gateway_state = {"connected": True, "mode": mode}
    session.save()
    return session


def add_secret(session, username="ib-user", password="ib-password"):
    return BrokerGatewaySessionSecret.objects.create(
        session=session,
        encrypted_username=encrypt_secret(username),
        encrypted_password=encrypt_secret(password),
        expires_at=timezone.now() + timedelta(minutes=5),
    )


@responses.activate
def test_gateway_client_rejects_parameterless_construction_and_isolates_two_fake_gateways():
    with pytest.raises((TypeError, GatewayRouteError)):
        GatewayClient()
    first = GatewayClient(GatewayRoute("session-a", "http://gateway-a/api/v1", "token-a"))
    second = GatewayClient(GatewayRoute("session-b", "http://gateway-b/api/v1", "token-b"))
    assert (first.base_url, first.token) != (second.base_url, second.token)
    for url, mode in (("http://gateway-a/api/v1/health/", "paper"), ("http://gateway-b/api/v1/health/", "live")):
        responses.get(url, json={"ok":True, "data":{"connected":True, "mode":mode}, "error":None, "meta":{}})
    assert first.health()["mode"] == "paper" and second.health()["mode"] == "live"
    assert [call.request.headers["Authorization"] for call in responses.calls] == ["Bearer token-a", "Bearer token-b"]


@pytest.mark.parametrize("status", [
    BrokerGatewaySession.Status.WAITING_FOR_LOGIN,
    BrokerGatewaySession.Status.WAITING_FOR_2FA,
    BrokerGatewaySession.Status.DISCONNECTED,
    BrokerGatewaySession.Status.ERROR,
])
def test_waiting_and_disconnected_sessions_cannot_trade_but_can_reconnect(status):
    session = make_session(f"Lifecycle {status}", "live", status=status)
    session.commands_enabled = True
    session.last_gateway_state = {"connected": False}
    session.save(update_fields=["commands_enabled", "last_gateway_state"])
    with pytest.raises(GatewaySessionUnavailable):
        GatewayClient(session, require_commands=True)
    assert GatewayClient(session, purpose="reconnect").base_url == session.internal_base_url


def test_creation_accepts_only_paper_live_encrypts_credentials_and_returns_no_secret(client, monkeypatch, django_capture_on_commit_callbacks):
    queued = []
    monkeypatch.setattr("apps.broker_gateway.views.provision_broker_session.delay", lambda session_id: queued.append(session_id))
    with django_capture_on_commit_callbacks(execute=True):
        for mode in ("Paper", "LIVE"):
            result = client.post("/api/v1/broker-sessions/", data=json.dumps({
                "display_name": mode, "username": "plain-user", "password": "plain-password", "mode": mode,
            }), content_type="application/json")
            assert result.status_code == 202
            body = result.content.decode()
            assert "plain-user" not in body and "plain-password" not in body
            assert "internal_base_url" not in body and "encrypted_" not in body
    invalid = client.post("/api/v1/broker-sessions/", data=json.dumps({
        "display_name": "bad", "username": "user", "password": "pass", "mode": "demo",
    }), content_type="application/json")
    assert invalid.status_code == 400
    secret = BrokerGatewaySessionSecret.objects.first()
    assert secret.encrypted_username != "plain-user" and decrypt_secret(secret.encrypted_username) == "plain-user"
    assert len(queued) == 2


@responses.activate
def test_qch_payload_and_bearer_auth_do_not_leak_into_error():
    url = "https://qch.example/api/apps/app-1/containers"
    responses.post(url, status=201, json={"id": "child-1", "name": "session-child", "status": "RUNNING"})
    qch = QCHBrokerClient()
    child = qch.create_container(
        name="session-child", image="registry/ibkr@sha256:abc",
        env={"IB_USERNAME": "secret-user", "IB_PASSWORD": "secret-password"}, network="traefik",
    )
    request = responses.calls[0].request
    payload = json.loads(request.body)
    assert child.id == "child-1"
    assert request.headers["Authorization"] == "Bearer qch-secret"
    assert payload["network"] == "traefik" and "command" not in payload
    assert payload["env"]["IB_PASSWORD"] == "secret-password" and "environment" not in payload
    responses.post(url, status=500, json={"error": "secret-password qch-secret"})
    with pytest.raises(QCHError) as error:
        qch.create_container(
            name="session-child-2", image="registry/ibkr@sha256:abc",
            env={"IB_PASSWORD": "secret-password"}, network="traefik",
        )
    assert "secret-password" not in str(error.value) and "qch-secret" not in str(error.value)


@responses.activate
def test_qch_direct_list_409_adoption_and_name_encoded_idempotent_delete():
    url = "https://qch.example/api/apps/app-1/containers"
    existing = {"id": "opaque-id", "name": "session child/one", "state": "running"}
    responses.get(url, status=200, json=[existing])
    assert QCHBrokerClient().list_containers()[0].name == existing["name"]

    responses.post(url, status=409, json={"error": "already exists"})
    responses.get(url, status=200, json={"containers": [existing]})
    adopted = QCHBrokerClient().create_container(name=existing["name"], image="registry/image@sha256:abc")
    assert adopted.id == "opaque-id" and adopted.status == "RUNNING"

    delete_url = f"{url}/session%20child%2Fone"
    responses.delete(delete_url, status=404)
    assert QCHBrokerClient().delete_container(existing["name"]) is False
    assert responses.calls[-1].request.url == delete_url


class FakeQCH:
    def __init__(self, existing=None, conflict=False):
        self.existing = existing
        self.conflict = conflict
        self.created = []
        self.deleted = []
        self.find_calls = 0

    def find_by_name(self, name):
        self.find_calls += 1
        if self.conflict and self.find_calls == 1:
            return None
        return self.existing

    def create_container(self, **payload):
        self.created.append(payload)
        if self.conflict:
            raise QCHConflict("exists")
        self.existing = QCHContainer("child", payload["name"], "RUNNING", {})
        return self.existing

    def delete_container(self, container_id):
        self.deleted.append(container_id)
        return True


class HealthyResponse:
    def raise_for_status(self):
        return None


def test_provision_consumes_secret_builds_required_environment_and_live_waits_for_2fa(monkeypatch):
    session = make_session("Live one", "live")
    add_secret(session)
    qch = FakeQCH()
    monkeypatch.setattr("apps.broker_gateway.services.requests.get", lambda *args, **kwargs: HealthyResponse())
    monkeypatch.setattr(GatewayClient, "health", lambda self: {"connected": False, "mode": "live"})
    assert provision_session(session.pk, qch_client=qch) == BrokerGatewaySession.Status.WAITING_FOR_2FA
    assert not BrokerGatewaySessionSecret.objects.filter(session=session).exists()
    environment = qch.created[0]["env"]
    assert environment["IB_USERNAME"] == "ib-user" and environment["IB_PASSWORD"] == "ib-password"
    assert environment["IBC_TRADING_MODE"] == "live" and environment["PORT"] == "8080"
    assert environment["APP_BASE_PATH"] == "" and environment["GATEWAY_SERVICE_TOKEN"] != environment["NOVNC_PASSWORD"]
    assert "command" not in qch.created[0]
    session.refresh_from_db()
    assert session.commands_enabled is False


def test_provision_adoption_deletes_secret_and_retryable_failure_keeps_it(monkeypatch):
    adopted = make_session("Adopt", "paper")
    add_secret(adopted)
    child = QCHContainer("existing-id", adopted.child_container_name, "RUNNING", {})
    qch = FakeQCH(existing=child)
    monkeypatch.setattr("apps.broker_gateway.services.requests.get", lambda *args, **kwargs: HealthyResponse())
    monkeypatch.setattr(GatewayClient, "health", lambda self: {"connected": False, "mode": "paper"})
    assert provision_session(adopted.pk, qch_client=qch) == BrokerGatewaySession.Status.WAITING_FOR_LOGIN
    adopted.refresh_from_db()
    assert adopted.child_container_id == "existing-id" and len(qch.created) == 0
    assert not BrokerGatewaySessionSecret.objects.filter(session=adopted).exists()

    failed = make_session("Failed", "paper")
    add_secret(failed)
    broken = FakeQCH()
    broken.create_container = lambda **kwargs: (_ for _ in ()).throw(QCHError("QCH unavailable", retryable=True))
    with pytest.raises(QCHError):
        provision_session(failed.pk, qch_client=broken)
    assert BrokerGatewaySessionSecret.objects.filter(session=failed).exists()
    record_provision_failure(failed.pk, QCHError("QCH unavailable", retryable=True), final=True)
    assert not BrokerGatewaySessionSecret.objects.filter(session=failed).exists()


def test_ambiguous_create_timeout_lists_expected_name_before_retry(monkeypatch):
    session = make_session("Ambiguous", "paper")
    add_secret(session)
    child = QCHContainer("created-despite-timeout", session.child_container_name, "RUNNING", {})
    qch = FakeQCH()

    def timed_out_create(**payload):
        qch.created.append(payload)
        qch.existing = child
        raise QCHError("QCH sub-container broker is unavailable", retryable=True)

    qch.create_container = timed_out_create
    monkeypatch.setattr("apps.broker_gateway.services.requests.get", lambda *args, **kwargs: HealthyResponse())
    monkeypatch.setattr(GatewayClient, "health", lambda self: {"connected": False, "mode": "paper"})
    assert provision_session(session.pk, qch_client=qch) == BrokerGatewaySession.Status.WAITING_FOR_LOGIN
    assert qch.find_calls == 2 and len(qch.created) == 1
    assert not BrokerGatewaySessionSecret.objects.filter(session=session).exists()


def test_stale_creating_session_is_requeued_and_expired_credentials_are_final(monkeypatch, settings):
    settings.BROKER_SESSION_CREATING_STALE_SECONDS = 60
    stale = make_session("Stale", "paper")
    add_secret(stale)
    old = timezone.now() - timedelta(minutes=5)
    BrokerGatewaySession.objects.filter(pk=stale.pk).update(updated_at=old, last_checked_at=None)
    queued = []
    monkeypatch.setattr("apps.broker_gateway.tasks.provision_broker_session.delay", lambda value: queued.append(value))
    result = monitor_broker_sessions()
    assert queued == [str(stale.pk)] and result["recovered_creating"] == [str(stale.pk)]

    expired = make_session("Expired", "live")
    add_secret(expired)
    BrokerGatewaySessionSecret.objects.filter(session=expired).update(expires_at=timezone.now() - timedelta(seconds=1))
    monitor_broker_sessions()
    expired.refresh_from_db()
    assert expired.status == BrokerGatewaySession.Status.LOGIN_FAILED
    assert expired.commands_enabled is False
    assert not BrokerGatewaySessionSecret.objects.filter(session=expired).exists()


class AccountsGateway:
    def __init__(self, account):
        self.account = account

    def accounts(self):
        return [{"account_id": self.account, "alias": self.account}]

    def account_summary(self):
        return [{"account": self.account, "tag": "NetLiquidation", "value": "1000", "currency": "USD"}]


def test_two_sessions_keep_accounts_portfolios_and_cursors_independent():
    first, second = make_session("First", status="CONNECTED"), make_session("Second", "live", status="CONNECTED")
    synchronize_accounts(first, AccountsGateway("DU-A"))
    synchronize_accounts(second, AccountsGateway("DU-B"))
    assert first.session_accounts.get().broker_account.account_id == "DU-A"
    assert second.session_accounts.get().broker_account.account_id == "DU-B"
    first_portfolio = TradingPortfolio.objects.get(gateway_session=first)
    second_portfolio = TradingPortfolio.objects.get(gateway_session=second)
    assert first_portfolio.account.account_id == "DU-A"
    assert second_portfolio.account.account_id == "DU-B"
    assert GatewayClient.for_portfolio(first_portfolio).base_url == first.internal_base_url
    assert GatewayClient.for_order(SimpleNamespace(intent=SimpleNamespace(portfolio=second_portfolio))).token == "token-Second"

    from apps.broker_gateway.sync import sync_events
    class Events:
        def __init__(self, session, account): self.gateway_session=session;self.account=account;self.acked=0
        def events(self, after=0): return [] if after else [{"id":1,"event_type":"snapshot.accounts","payload":{"value":[{"account_id":self.account}]}}]
        def ack_events(self, sequence): self.acked=sequence
    assert sync_events(Events(first,"DU-A")) == 1 and sync_events(Events(second,"DU-B")) == 1
    assert set(BrokerSyncCursor.objects.values_list("session_id","last_sequence")) == {(first.pk,1),(second.pk,1)}


def test_reconnect_and_idempotent_delete_leave_other_session_intact(client, monkeypatch):
    first, second = make_session("Delete", status="CONNECTED"), make_session("Keep", status="CONNECTED")
    first.child_container_id = "opaque-delete-id"; first.save(update_fields=["child_container_id"])
    account = BrokerAccount.objects.create(account_id="DU-DELETE", is_reconciled=True)
    BrokerSessionAccount.objects.create(session=first, broker_account=account)
    TradingPortfolio.objects.create(name="Delete route", account=account, gateway_session=first)
    monkeypatch.setattr(GatewayClient, "reconnect", lambda self: {"command_id": 7, "status": "PENDING"})
    reconnect = client.post(f"/api/v1/broker-sessions/{first.pk}/reconnect/", data="{}", content_type="application/json")
    assert reconnect.status_code == 202
    qch = FakeQCH()
    removed, changed = delete_session(first.pk, qch_client=qch)
    removed_again, changed_again = delete_session(first.pk, qch_client=qch)
    second.refresh_from_db()
    assert changed is True and changed_again is False and removed_again.status == "DELETED"
    assert qch.deleted == [first.child_container_name] and second.status == "CONNECTED"
    assert BrokerAccount.objects.get(pk=account.pk).is_reconciled is False


def _http_scope(session_id, asset, token, extra_query=""):
    query = f"token={token}{extra_query}".encode()
    return {"type":"http","method":"GET","path":f"/api/v1/broker-sessions/{session_id}/novnc/{asset}",
        "query_string":query,"headers":[],"scheme":"http"}


@override_settings(
    APP_BASE_PATH="/trading_eng_backend",
    PUBLIC_BASE_URL="https://qfsplatform.com/trading_eng_backend",
)
def test_public_novnc_url_and_asgi_connect_page_use_exact_prefix_once(monkeypatch):
    from apps.broker_gateway import proxy, views

    session = make_session("Prefix", "live", status=BrokerGatewaySession.Status.WAITING_FOR_2FA)
    request = RequestFactory().get(
        f"/api/v1/broker-sessions/{session.pk}/",
        HTTP_HOST="qfsplatform.com",
        HTTP_X_FORWARDED_PROTO="https",
        HTTP_X_FORWARDED_PREFIX="/trading_eng_backend",
    )
    public_url = views._public_novnc_url(request, session)
    expected_connect = (
        f"https://qfsplatform.com/trading_eng_backend/api/v1/broker-sessions/{session.pk}/novnc/connect/"
    )
    assert public_url.startswith(expected_connect + "#access_token=")
    assert public_url.count("/trading_eng_backend") == 1
    assert "trading_eng_gateway" not in public_url

    async def load(_):
        return session

    monkeypatch.setattr(proxy, "_load_session", load)

    async def fallback(scope, receive, send):
        raise AssertionError("ASGI noVNC route fell through to Django")

    async def run(scope):
        sent = []

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            sent.append(message)

        await proxy.BrokerProxyRouter(fallback)(scope, receive, send)
        return sent

    preserved_scope = {
        "type": "http",
        "method": "GET",
        "scheme": "https",
        "path": f"/trading_eng_backend/api/v1/broker-sessions/{session.pk}/novnc/connect",
        "query_string": b"",
        "headers": [(b"host", b"qfsplatform.com")],
    }
    preserved = asyncio.run(run(preserved_scope))
    page = preserved[-1]["body"].decode()
    prefix = f"/trading_eng_backend/api/v1/broker-sessions/{session.pk}/novnc"
    assert preserved[0]["status"] == 200
    assert f'"authorize": "{prefix}/authorize/"' in page
    assert f'"vnc": "{prefix}/vnc.html"' in page
    assert f'"websockify": "{prefix.lstrip("/")}/websockify"' in page
    assert "../authorize/" not in page and "../vnc.html" not in page

    stripped_scope = {
        **preserved_scope,
        "path": f"/api/v1/broker-sessions/{session.pk}/novnc/connect",
        "headers": [(b"host", b"qfsplatform.com"), (b"x-forwarded-prefix", b"/trading_eng_backend")],
    }
    stripped = asyncio.run(run(stripped_scope))
    assert stripped[-1]["body"] == preserved[-1]["body"]

    websocket_scope = {
        "type": "websocket",
        "path": f"/trading_eng_backend/api/v1/broker-sessions/{session.pk}/novnc/websockify",
        "query_string": b"",
        "headers": [],
    }
    assert proxy._route(websocket_scope) == (str(session.pk), "websockify", prefix)


def test_novnc_http_binary_forwarding_token_expiry_and_ssrf_rejection(monkeypatch):
    from apps.broker_gateway import proxy
    session = SimpleNamespace(pk="11111111-1111-1111-1111-111111111111", child_container_name="safe-child")
    async def load(_): return session
    monkeypatch.setattr(proxy,"_load_session",load)
    real_validate=proxy.validate_novnc_access_token
    monkeypatch.setattr(proxy,"validate_novnc_access_token",lambda sid,value: real_validate(sid,value,now=100))
    token,_=issue_novnc_access_token(session.pk,now=100)
    captured=[]
    class FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): return None
        async def request(self,method,url,**kwargs):
            captured.append(url);return httpx.Response(200,content=b"\x00\xffasset",headers={"content-type":"application/octet-stream"})
    monkeypatch.setattr(proxy.httpx,"AsyncClient",lambda **kwargs:FakeClient())
    async def run(scope):
        sent=[]
        async def receive(): return {"type":"http.request","body":b"","more_body":False}
        async def send(message): sent.append(message)
        await proxy.proxy_http(scope,receive,send,proxy._route(scope))
        return sent
    valid=asyncio.run(run(_http_scope(session.pk,"app/ui.js",token)))
    assert valid[-1]["body"] == b"\x00\xffasset" and captured[0].startswith("http://safe-child:8080/")
    rejected=asyncio.run(run(_http_scope(session.pk,"app/ui.js",token,"&host=evil.example&port=22")))
    assert rejected[0]["status"] == 400
    expired,_=issue_novnc_access_token(session.pk,ttl_seconds=30,now=1)
    expired_result=asyncio.run(run(_http_scope(session.pk,"app/ui.js",expired)))
    assert expired_result[0]["status"] == 403


def test_novnc_websocket_preserves_binary_frames(monkeypatch):
    from apps.broker_gateway import proxy
    session = SimpleNamespace(pk="22222222-2222-2222-2222-222222222222", child_container_name="safe-child")
    token,_=issue_novnc_access_token(session.pk)
    async def load(_): return session
    monkeypatch.setattr(proxy,"_load_session",load)
    class Upstream:
        subprotocol="binary"
        def __init__(self): self.sent=[];self.iterated=False
        async def send(self,data): self.sent.append(data)
        async def close(self,code=1000): return None
        def __aiter__(self): return self
        async def __anext__(self):
            if self.iterated: raise StopAsyncIteration
            self.iterated=True;return b"\x00\x01\xff"
    upstream=Upstream()
    class Context:
        async def __aenter__(self): return upstream
        async def __aexit__(self,*args): return None
    monkeypatch.setattr(proxy,"websocket_connect",lambda *args,**kwargs:Context())
    scope={"type":"websocket","path":f"/api/v1/broker-sessions/{session.pk}/novnc/websockify",
        "query_string":f"token={token}".encode(),"headers":[],"subprotocols":["binary"]}
    messages=iter([{"type":"websocket.connect"},{"type":"websocket.receive","bytes":b"\x10\x11"},{"type":"websocket.disconnect","code":1000}])
    sent=[]
    async def receive(): return next(messages)
    async def send(message): sent.append(message)
    asyncio.run(proxy.proxy_websocket(scope,receive,send,proxy._route(scope)))
    assert {"type":"websocket.send","bytes":b"\x00\x01\xff"} in sent


def test_novnc_proxy_terminates_vnc_auth_without_returning_password_or_challenge():
    from apps.broker_gateway import proxy

    challenge = bytes(range(16))

    class Upstream:
        def __init__(self):
            self.frames = iter([b"RFB 003.008\n", b"\x01\x02", challenge, b"\x00\x00\x00\x00"])
            self.sent = []
        def __aiter__(self): return self
        async def __anext__(self):
            try: return next(self.frames)
            except StopIteration: raise StopAsyncIteration
        async def send(self, value): self.sent.append(value)

    upstream = Upstream()
    client_messages = iter([
        {"type":"websocket.receive", "bytes":b"RFB 003.008\n"},
        {"type":"websocket.receive", "bytes":b"\x01"},
    ])
    browser = []
    async def receive(): return next(client_messages)
    async def send(message): browser.append(message)

    asyncio.run(proxy._prepare_rfb_connection(upstream, receive, send, encrypt_secret("vnc-pass")))
    browser_bytes = [message["bytes"] for message in browser]
    assert browser_bytes == [b"RFB 003.008\n", b"\x01\x01", b"\x00\x00\x00\x00"]
    assert upstream.sent[:2] == [b"RFB 003.008\n", b"\x02"]
    assert len(upstream.sent[2]) == 16 and upstream.sent[2] != challenge
    assert b"vnc-pass" not in b"".join(browser_bytes)
