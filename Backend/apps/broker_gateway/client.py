import time
import hashlib
import json
import requests
from django.conf import settings

class GatewayError(RuntimeError): pass

class GatewayClient:
    def __init__(self, base_url=None, token=None, session=None):
        self.base_url = (base_url or settings.IB_GATEWAY_SERVICE_URL).rstrip("/")
        self.token = token or settings.GATEWAY_SERVICE_TOKEN
        self.session = session or requests.Session()

    def request(self, method, path, *, idempotency_key=None, retries=2, **kwargs):
        headers = {"Authorization": f"Bearer {self.token}", **kwargs.pop("headers", {})}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        safe = method.upper() == "GET"
        for attempt in range(retries + 1):
            try:
                response = self.session.request(method, f"{self.base_url}/{path.lstrip('/')}", headers=headers, timeout=10, **kwargs)
                if response.status_code >= 500 and safe and attempt < retries:
                    time.sleep(0.05 * (2 ** attempt)); continue
                response.raise_for_status()
                body = response.json()
                if not body.get("ok", False): raise GatewayError(str(body.get("error")))
                return body.get("data")
            except requests.RequestException as exc:
                if not safe or attempt >= retries: raise GatewayError(str(exc)) from exc
                time.sleep(0.05 * (2 ** attempt))

    def health(self): return self.request("GET", "health/")
    def positions(self): return self.request("GET", "positions/")
    def executions(self): return self.request("GET", "executions/")
    def accounts(self): return self.request("GET", "accounts/")
    def account_summary(self): return self.request("GET", "account-summary/")
    def open_orders(self): return self.request("GET", "open-orders/")
    def completed_orders(self): return self.request("GET", "completed-orders/")
    def command(self, command_id): return self.request("GET", f"commands/{int(command_id)}/")
    def wait_for_command(self, queued, timeout=20):
        command_id=int(queued["command_id"]);deadline=time.monotonic()+timeout
        current=queued
        while current.get("status") not in {"COMPLETED","FAILED","UNKNOWN"} and time.monotonic()<deadline:
            time.sleep(0.1);current=self.command(command_id)
        # Enqueue responses intentionally contain only the command id and status.  When an
        # idempotency key replays an already-terminal command, load its persisted result
        # before returning instead of treating the absent result as an empty success.
        if current.get("status") in {"COMPLETED","FAILED","UNKNOWN"} and "result" not in current:
            current=self.command(command_id)
        if current.get("status") in {"FAILED","UNKNOWN"}:raise GatewayError(current.get("last_error") or f"Gateway command {command_id} failed")
        if current.get("status")!="COMPLETED":raise GatewayError(f"Gateway command {command_id} timed out")
        return current.get("result") or {}
    def search_contracts(self, query):
        query=str(query).strip();digest=hashlib.sha256(query.casefold().encode()).hexdigest()[:32]
        queued=self.request("POST", "contracts/search/", json={"query":query},idempotency_key=f"contract-search:{digest}",retries=0)
        return self.wait_for_command(queued).get("results",[])
    def events(self, after=0): return self.request("GET", f"events/?after={int(after)}")
    def ack_events(self, sequence): return self.request("POST", "events/ack/", json={"sequence":int(sequence)}, idempotency_key=f"events-ack:{int(sequence)}", retries=0)
    def place_order(self, payload, key): return self.request("POST", "orders/", json=payload, idempotency_key=key, retries=0)
    def modify_order(self, internal_id, payload, key): return self.request("PATCH", f"orders/{internal_id}/", json=payload, idempotency_key=key, retries=0)
    def cancel_order(self, internal_id, key): return self.request("POST", f"orders/{internal_id}/cancel/", json={}, idempotency_key=key, retries=0)
    def qualify_contract(self, payload, key): return self.request("POST", "contracts/qualify/", json=payload, idempotency_key=key, retries=0)
    def qualify_contract_exact(self, payload, key):
        queued=self.qualify_contract(payload,key)
        return self.wait_for_command(queued)
    def historical_bars(self, payload, timeout=60):
        canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str)
        digest=hashlib.sha256(canonical.encode()).hexdigest()[:40]
        queued=self.request("POST","market-data/history/",json=payload,
                            idempotency_key=f"historical-data:{digest}",retries=0)
        return self.wait_for_command(queued,timeout=timeout)
    def subscribe_market_data(self,payload,key):return self.request("POST","market-data/subscriptions/",json=payload,idempotency_key=key,retries=0)
    def cancel_market_data(self,payload,key):return self.request("POST","market-data/subscriptions/cancel/",json=payload,idempotency_key=key,retries=0)
