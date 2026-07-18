import time
from datetime import date, timedelta
from .base import BrokerAdapter

class MockBrokerAdapter(BrokerAdapter):
    def __init__(self): self.connected = False; self.next_order_id = 1000; self.orders = {}; self.subscriptions = {}; self.market_events=[]; self.order_events=[]; self.killed = False
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
    def historical_bars(self, payload):
        count=min(int(str(payload.get("duration", "30 D")).split()[0]), 30)
        end=date.today()
        bars=[]
        for offset in range(count, 0, -1):
            day=end-timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            price=100 + len(bars)
            bars.append({"date":day.isoformat(),"open":str(price),"high":str(price+1),
                         "low":str(price-1),"close":str(price),"volume":"1000000",
                         "bar_count":1,"average":str(price)})
        return {"conid":int(payload["conid"]),"symbol":payload["symbol"],"provider":"IBKR",
                "what_to_show":payload.get("what_to_show","TRADES"),"bars":bars}
    def subscribe_market_data(self,payload):
        key=payload["subscription_key"];runtime_key=payload.get("gateway_subscription_key") or key
        self.subscriptions[runtime_key]=dict(payload)
        return {"subscription_key":key,"gateway_subscription_key":runtime_key,"state":"ACTIVE","historical_bar_count":0,
            "provider_generation":str(payload.get("provider_generation") or ""),"probe":bool(payload.get("probe"))}
    def cancel_market_data(self,payload):
        key=payload["subscription_key"]
        matches=[name for name,item in self.subscriptions.items() if item.get("subscription_key")==key]
        for name in matches:self.subscriptions.pop(name,None)
        return {"subscription_key":key,"state":"INACTIVE","cancelled":len(matches)}
    def drain_market_events(self):
        events,self.market_events=self.market_events,[];return events
    def drain_order_events(self):
        events,self.order_events=self.order_events,[];return events
    def place_order(self, payload):
        if self.killed: raise RuntimeError("Gateway kill switch is active")
        self.next_order_id += 1; oid = str(self.next_order_id)
        self.orders[payload["internal_id"]] = {**payload, "broker_order_id":oid, "status":"Submitted"}
        return self.orders[payload["internal_id"]]
    def modify_order(self, payload):
        current = self.orders[payload["internal_id"]]; current.update(payload); current["status"]="Submitted"; return current
    def cancel_order(self, payload):
        current = self.orders[payload["internal_id"]]; current["status"]="Cancelled"
        self.order_events.append({"source_event_id":f"mock-cancel:{payload['internal_id']}","internal_id":payload["internal_id"],
            "broker_order_id":current["broker_order_id"],"permanent_id":"","broker_status":"Cancelled","error_code":"",
            "error_message":"","why_held":"","warning_text":"","advanced_reject":None,"trade_log":[],
            "occurred_at":None,"operator_requested":True})
        return current
    def refresh_state(self): return {"accounts":[], "account_summary":[], "positions":[], "open_orders":list(self.orders.values()), "completed_orders":[], "executions":[], "reconciled":True}
    def wait(self, seconds): time.sleep(seconds)
