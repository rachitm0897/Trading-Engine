from dataclasses import dataclass
import hashlib
import json
import time

import requests

from .crypto import decrypt_secret


class GatewayError(RuntimeError):
    pass


class GatewayRouteError(GatewayError):
    pass


class GatewaySessionUnavailable(GatewayRouteError):
    pass


class GatewayTransportError(GatewayError):
    pass


class GatewayCommandRejected(GatewayError):
    pass


@dataclass(frozen=True)
class GatewayRoute:
    session_id: str
    base_url: str
    service_token: str

    def __post_init__(self):
        if not self.session_id or not self.base_url or not self.service_token:
            raise GatewayRouteError("A gateway route requires session identity, URL, and service token")


def route_for_session(gateway_session, *, purpose="read"):
    from .models import BrokerGatewaySession

    if gateway_session is None:
        raise GatewayRouteError("A broker gateway session is required")
    if gateway_session.deleted_at or gateway_session.status in {
        BrokerGatewaySession.Status.STOPPING,
        BrokerGatewaySession.Status.DELETED,
    }:
        raise GatewaySessionUnavailable("The broker gateway session has been deleted or is stopping")
    if purpose == "command":
        connected = (
            gateway_session.status == BrokerGatewaySession.Status.CONNECTED
            and gateway_session.commands_enabled
            and bool((gateway_session.last_gateway_state or {}).get("connected"))
        )
        if not connected:
            raise GatewaySessionUnavailable("Trading commands require a connected and valid broker gateway session")
    elif purpose == "reconnect" and gateway_session.status not in {
        BrokerGatewaySession.Status.STARTING,
        BrokerGatewaySession.Status.WAITING_FOR_LOGIN,
        BrokerGatewaySession.Status.WAITING_FOR_2FA,
        BrokerGatewaySession.Status.CONNECTED,
        BrokerGatewaySession.Status.DISCONNECTED,
        BrokerGatewaySession.Status.LOGIN_FAILED,
        BrokerGatewaySession.Status.ERROR,
    }:
        raise GatewaySessionUnavailable("This broker gateway session is not eligible for reconnect")
    if not gateway_session.internal_base_url or not gateway_session.encrypted_gateway_token:
        raise GatewaySessionUnavailable("The broker gateway session has not been provisioned")
    return GatewayRoute(
        session_id=str(gateway_session.pk),
        base_url=gateway_session.internal_base_url,
        service_token=decrypt_secret(gateway_session.encrypted_gateway_token),
    )


class GatewayClient:
    """Authenticated client bound to one immutable broker-session route."""

    def __init__(self, route, *, http_session=None, require_commands=False, purpose=None):
        self.gateway_session = None
        self.purpose = purpose or ("command" if require_commands else "read")
        if isinstance(route, GatewayRoute):
            resolved = route
        elif hasattr(route, "internal_base_url"):
            self.gateway_session = route
            resolved = route_for_session(route, purpose=self.purpose)
        else:
            raise GatewayRouteError("GatewayClient requires a broker session or explicit GatewayRoute")
        self.route = resolved
        self.base_url = resolved.base_url.rstrip("/")
        self.token = resolved.service_token
        self.http = http_session or requests.Session()

    def _require_session_purpose(self, purpose):
        if self.gateway_session is not None:
            route_for_session(self.gateway_session, purpose=purpose)

    @classmethod
    def for_portfolio(cls, portfolio, *, require_commands=False, http_session=None):
        gateway_session = getattr(portfolio, "gateway_session", None)
        if gateway_session is None:
            raise GatewaySessionUnavailable("Portfolio is not bound to an IBKR gateway session")
        mapping_exists = gateway_session.session_accounts.filter(broker_account_id=portfolio.account_id, available=True).exists()
        if not mapping_exists:
            raise GatewaySessionUnavailable("Portfolio account is not available through its bound gateway session")
        return cls(gateway_session, require_commands=require_commands, http_session=http_session)

    @classmethod
    def for_order(cls, order, *, require_commands=True, http_session=None):
        portfolio = order.intent.portfolio
        return cls.for_portfolio(portfolio, require_commands=require_commands, http_session=http_session)

    def _session_key(self, key):
        return f"session:{self.route.session_id}:{key}"[:255]

    def request(self, method, path, *, idempotency_key=None, retries=2, timeout=10, **kwargs):
        headers = {"Authorization": f"Bearer {self.token}", **kwargs.pop("headers", {})}
        if idempotency_key:
            headers["Idempotency-Key"] = self._session_key(idempotency_key)
        safe = method.upper() == "GET"
        for attempt in range(retries + 1):
            try:
                response = self.http.request(
                    method,
                    f"{self.base_url}/{path.lstrip('/')}",
                    headers=headers,
                    timeout=timeout,
                    **kwargs,
                )
                if response.status_code >= 500 and safe and attempt < retries:
                    time.sleep(0.05 * (2 ** attempt))
                    continue
                if 400 <= response.status_code < 500:
                    try:
                        body = response.json()
                        error = body.get("error") or {}
                        message = error.get("message") if isinstance(error, dict) else error
                    except (TypeError, ValueError):
                        message = response.text
                    raise GatewayCommandRejected(
                        str(message or f"Gateway rejected request with HTTP {response.status_code}")
                    )
                response.raise_for_status()
                body = response.json()
                if not body.get("ok", False):
                    error = body.get("error") or {}
                    raise GatewayError(str(error.get("message") if isinstance(error, dict) else error))
                return body.get("data")
            except requests.RequestException as exc:
                if not safe or attempt >= retries:
                    raise GatewayTransportError("Broker gateway request failed") from exc
                time.sleep(0.05 * (2 ** attempt))

    def health(self):
        return self.request("GET", "health/")

    def session_state(self):
        return self.request("GET", "session/")

    def reconnect(self):
        self._require_session_purpose("reconnect")
        return self.request("POST", "session/reconnect/", json={}, idempotency_key=f"reconnect:{int(time.time())}", retries=0)

    def positions(self):
        return self.request("GET", "positions/")

    def executions(self):
        return self.request("GET", "executions/")

    def accounts(self):
        return self.request("GET", "accounts/")

    def account_summary(self):
        return self.request("GET", "account-summary/")

    def open_orders(self):
        return self.request("GET", "open-orders/")

    def completed_orders(self):
        return self.request("GET", "completed-orders/")

    def order_state(self, internal_id):
        return self.request("GET", f"orders/{internal_id}/state/")

    def command(self, command_id):
        return self.request("GET", f"commands/{int(command_id)}/")

    def wait_for_command(self, queued, timeout=20):
        command_id = int(queued["command_id"])
        deadline = time.monotonic() + timeout
        current = queued
        while current.get("status") not in {"COMPLETED", "FAILED", "UNKNOWN"} and time.monotonic() < deadline:
            time.sleep(0.1)
            current = self.command(command_id)
        if current.get("status") in {"COMPLETED", "FAILED", "UNKNOWN"} and "result" not in current:
            current = self.command(command_id)
        if current.get("status") in {"FAILED", "UNKNOWN"}:
            raise GatewayError(current.get("last_error") or f"Gateway command {command_id} failed")
        if current.get("status") != "COMPLETED":
            raise GatewayError(f"Gateway command {command_id} timed out")
        return current.get("result") or {}

    def search_contracts(self, query):
        self._require_session_purpose("command")
        query = str(query).strip()
        digest = hashlib.sha256(query.casefold().encode()).hexdigest()[:32]
        queued = self.request(
            "POST", "contracts/search/", json={"query": query}, idempotency_key=f"contract-search:{digest}", retries=0
        )
        return self.wait_for_command(queued).get("results", [])

    def events(self, after=0):
        return self.request("GET", f"events/?after={int(after)}")

    def ack_events(self, sequence):
        return self.request(
            "POST", "events/ack/", json={"sequence": int(sequence)}, idempotency_key=f"events-ack:{int(sequence)}", retries=0
        )

    def place_order(self, payload, key):
        self._require_session_purpose("command")
        return self.request("POST", "orders/", json=payload, idempotency_key=key, retries=0)

    def modify_order(self, internal_id, payload, key):
        self._require_session_purpose("command")
        return self.request("PATCH", f"orders/{internal_id}/", json=payload, idempotency_key=key, retries=0)

    def cancel_order(self, internal_id, key):
        self._require_session_purpose("command")
        return self.request("POST", f"orders/{internal_id}/cancel/", json={}, idempotency_key=key, retries=0)

    def qualify_contract(self, payload, key):
        self._require_session_purpose("command")
        return self.request("POST", "contracts/qualify/", json=payload, idempotency_key=key, retries=0)

    def qualify_contract_exact(self, payload, key):
        return self.wait_for_command(self.qualify_contract(payload, key))

    def historical_bars(self, payload, timeout=60):
        self._require_session_purpose("command")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:40]
        queued = self.request(
            "POST", "market-data/history/", json=payload, idempotency_key=f"historical-data:{digest}", retries=0
        )
        return self.wait_for_command(queued, timeout=timeout)

    def historical_schedule(self, payload, timeout=30):
        self._require_session_purpose("command")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:40]
        queued = self.request(
            "POST", "market-data/schedule/", json=payload, idempotency_key=f"historical-schedule:{digest}", retries=0
        )
        return self.wait_for_command(queued, timeout=timeout)

    def subscribe_market_data(self, payload, key):
        self._require_session_purpose("command")
        return self.request("POST", "market-data/subscriptions/", json=payload, idempotency_key=key, retries=0)

    def cancel_market_data(self, payload, key):
        self._require_session_purpose("command")
        return self.request("POST", "market-data/subscriptions/cancel/", json=payload, idempotency_key=key, retries=0)
