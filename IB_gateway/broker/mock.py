from .base import BrokerAdapter

class MockBrokerAdapter(BrokerAdapter):
    def __init__(self): self.connected = False; self.next_order_id = 1000; self.orders = {}; self.killed = False
    def connect(self): self.connected = True; return {"connected":True}
    def disconnect(self): self.connected = False
    def is_connected(self): return self.connected
    def qualify_contract(self, payload):
        symbol = payload["symbol"]
        return {**payload, "conid": abs(hash((symbol, payload.get("exchange","SMART")))) % 2_000_000_000, "qualified":True}
    def place_order(self, payload):
        if self.killed: raise RuntimeError("Gateway kill switch is active")
        self.next_order_id += 1; oid = str(self.next_order_id)
        self.orders[payload["internal_id"]] = {**payload, "broker_order_id":oid, "status":"Submitted"}
        return self.orders[payload["internal_id"]]
    def modify_order(self, payload):
        current = self.orders[payload["internal_id"]]; current.update(payload); current["status"]="Submitted"; return current
    def cancel_order(self, payload):
        current = self.orders[payload["internal_id"]]; current["status"]="Cancelled"; return current
    def refresh_state(self): return {"accounts":["DU-MOCK"], "positions":[], "open_orders":list(self.orders.values()), "executions":[], "reconciled":True}

