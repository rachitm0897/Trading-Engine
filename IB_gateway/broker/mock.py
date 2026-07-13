import time
from .base import BrokerAdapter

class MockBrokerAdapter(BrokerAdapter):
    def __init__(self): self.connected = False; self.next_order_id = 1000; self.orders = {}; self.subscriptions = {}; self.market_events=[]; self.killed = False
    def connect(self): self.connected = True; return {"connected":True}
    def disconnect(self): self.connected = False
    def is_connected(self): return self.connected
    def search_contracts(self, query):
        symbol = str(query).strip().upper()
        rows = [{"symbol":symbol,"local_symbol":symbol,"conid":abs(hash((symbol,"NASDAQ"))) % 2_000_000_000,
            "asset_class":"STK","exchange":"SMART","primary_exchange":"NASDAQ","currency":"USD",
            "description":f"{symbol} mock corporation"}]
        if symbol == "BHP":
            rows.append({"symbol":"BHP","local_symbol":"BHP","conid":abs(hash((symbol,"ASX"))) % 2_000_000_000,
                "asset_class":"STK","exchange":"SMART","primary_exchange":"ASX","currency":"AUD",
                "description":"BHP Group Limited"})
        return rows
    def qualify_contract(self, payload):
        symbol = payload["symbol"]
        return {**payload, "local_symbol":payload.get("local_symbol") or symbol,
            "conid":int(payload.get("conid") or abs(hash((symbol, payload.get("exchange","SMART")))) % 2_000_000_000),
            "primary_exchange":payload.get("primary_exchange") or "NASDAQ",
            "description":payload.get("description") or f"{symbol} mock corporation","qualified":True}
    def subscribe_market_data(self,payload):
        key=payload["subscription_key"];self.subscriptions[key]=dict(payload)
        return {"subscription_key":key,"state":"ACTIVE","historical_bar_count":0}
    def cancel_market_data(self,payload):
        key=payload["subscription_key"];self.subscriptions.pop(key,None)
        return {"subscription_key":key,"state":"INACTIVE"}
    def drain_market_events(self):
        events,self.market_events=self.market_events,[];return events
    def place_order(self, payload):
        if self.killed: raise RuntimeError("Gateway kill switch is active")
        self.next_order_id += 1; oid = str(self.next_order_id)
        self.orders[payload["internal_id"]] = {**payload, "broker_order_id":oid, "status":"Submitted"}
        return self.orders[payload["internal_id"]]
    def modify_order(self, payload):
        current = self.orders[payload["internal_id"]]; current.update(payload); current["status"]="Submitted"; return current
    def cancel_order(self, payload):
        current = self.orders[payload["internal_id"]]; current["status"]="Cancelled"; return current
    def refresh_state(self): return {"accounts":[], "account_summary":[], "positions":[], "open_orders":list(self.orders.values()), "completed_orders":[], "executions":[], "reconciled":True}
    def wait(self, seconds): time.sleep(seconds)
