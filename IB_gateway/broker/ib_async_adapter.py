from django.conf import settings
from .base import BrokerAdapter

class IBAsyncBrokerAdapter(BrokerAdapter):
    def __init__(self):
        from ib_async import IB
        self.ib = IB(); self.contracts = {}; self.trades = {}
    def connect(self):
        self.ib.connect("127.0.0.1", settings.TWS_PORT, clientId=settings.IBKR_CLIENT_ID, readonly=False, timeout=15)
        return {"connected":self.ib.isConnected()}
    def disconnect(self): self.ib.disconnect()
    def is_connected(self): return self.ib.isConnected()
    def _contract(self, payload):
        from ib_async import Stock, Forex, Future
        asset = payload.get("asset_class", "STK")
        if asset == "CASH": return Forex(payload["symbol"], exchange=payload.get("exchange", "IDEALPRO"))
        if asset == "FUT": return Future(payload["symbol"], payload.get("expiry", ""), exchange=payload["exchange"], currency=payload.get("currency", "USD"))
        return Stock(payload["symbol"], payload.get("exchange", "SMART"), payload.get("currency", "USD"))
    def qualify_contract(self, payload):
        contract = self._contract(payload); qualified = self.ib.qualifyContracts(contract)
        if not qualified: raise RuntimeError("Contract qualification returned no result")
        contract = qualified[0]; self.contracts[str(contract.conId)] = contract
        return {"conid":contract.conId, "symbol":contract.symbol, "exchange":contract.exchange, "currency":contract.currency, "qualified":True}
    def _order(self, payload):
        from ib_async import MarketOrder, LimitOrder, StopOrder, StopLimitOrder
        action, qty, tif = payload["side"], float(payload["quantity"]), payload.get("time_in_force", "DAY")
        typ = payload.get("order_type", "MKT")
        if typ == "LMT": return LimitOrder(action, qty, float(payload["limit_price"]), tif=tif)
        if typ == "STP": return StopOrder(action, qty, float(payload["stop_price"]), tif=tif)
        if typ == "STP_LMT": return StopLimitOrder(action, qty, float(payload["limit_price"]), float(payload["stop_price"]), tif=tif)
        return MarketOrder(action, qty, tif=tif)
    def place_order(self, payload):
        contract = self.contracts.get(str(payload.get("conid"))) or self._contract(payload)
        trade = self.ib.placeOrder(contract, self._order(payload)); self.trades[payload["internal_id"]] = trade
        return {"internal_id":payload["internal_id"], "broker_order_id":str(trade.order.orderId), "permanent_id":str(trade.order.permId or ""), "status":trade.orderStatus.status}
    def modify_order(self, payload):
        trade = self.trades[payload["internal_id"]]
        for source, dest in [("quantity","totalQuantity"),("limit_price","lmtPrice"),("stop_price","auxPrice")]:
            if source in payload: setattr(trade.order, dest, float(payload[source]))
        trade = self.ib.placeOrder(trade.contract, trade.order); return {"broker_order_id":str(trade.order.orderId), "status":trade.orderStatus.status}
    def cancel_order(self, payload):
        trade = self.trades[payload["internal_id"]]; self.ib.cancelOrder(trade.order); return {"broker_order_id":str(trade.order.orderId), "status":"PendingCancel"}
    def refresh_state(self):
        return {"accounts":self.ib.managedAccounts(), "positions":[{"account":p.account,"conid":p.contract.conId,"quantity":p.position,"average_cost":p.avgCost} for p in self.ib.positions()], "open_orders":[{"broker_order_id":t.order.orderId,"status":t.orderStatus.status} for t in self.ib.openTrades()], "executions":[{"execution_id":f.execution.execId,"broker_order_id":f.execution.orderId,"quantity":f.execution.shares,"price":f.execution.price} for f in self.ib.fills()], "reconciled":True}

