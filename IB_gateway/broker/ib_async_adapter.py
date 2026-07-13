from django.conf import settings
from collections import deque
from datetime import date, datetime, time, timedelta, timezone
from .base import BrokerAdapter

class IBAsyncBrokerAdapter(BrokerAdapter):
    def __init__(self):
        from ib_async import IB
        self.ib = IB(); self.contracts = {}; self.trades = {}; self.market_subscriptions={};self.market_events=deque()
    def connect(self):
        self.ib.connect("127.0.0.1", settings.TWS_PORT, clientId=settings.IBKR_CLIENT_ID, readonly=False, timeout=15)
        return {"connected":self.ib.isConnected()}
    def disconnect(self): self.ib.disconnect()
    def is_connected(self): return self.ib.isConnected()
    def _contract(self, payload):
        from ib_async import Contract, Stock, Forex, Future
        if payload.get("conid"):
            return Contract(conId=int(payload["conid"]), exchange=payload.get("exchange", ""), currency=payload.get("currency", ""))
        asset = payload.get("asset_class", "STK")
        if asset == "CASH": return Forex(payload["symbol"], exchange=payload.get("exchange", "IDEALPRO"))
        if asset == "FUT": return Future(payload["symbol"], payload.get("expiry", ""), exchange=payload["exchange"], currency=payload.get("currency", "USD"))
        return Stock(payload["symbol"], payload.get("exchange", "SMART"), payload.get("currency", "USD"))
    @staticmethod
    def _contract_data(contract, details=None):
        return {"conid":contract.conId,"symbol":contract.symbol,"local_symbol":contract.localSymbol,
            "asset_class":contract.secType,"exchange":contract.exchange or contract.primaryExchange,
            "primary_exchange":contract.primaryExchange,"currency":contract.currency,
            "description":getattr(details,"longName","") or getattr(details,"marketName","") or ""}
    def _details(self, contract):
        details = self.ib.reqContractDetails(contract)
        return next((item for item in details if item.contract.conId == contract.conId), details[0] if details else None)
    def search_contracts(self, query):
        matches = self.ib.reqMatchingSymbols(str(query).strip())
        results = []
        seen = set()
        for match in matches:
            contract = match.contract
            if contract.conId <= 0 or contract.conId in seen:
                continue
            seen.add(contract.conId)
            details = self._details(contract)
            exact = details.contract if details else contract
            results.append(self._contract_data(exact, details))
        return results
    def qualify_contract(self, payload):
        contract = self._contract(payload); qualified = self.ib.qualifyContracts(contract)
        if not qualified: raise RuntimeError("Contract qualification returned no result")
        contract = qualified[0]; self.contracts[str(contract.conId)] = contract
        return {**self._contract_data(contract, self._details(contract)), "qualified":True}
    @staticmethod
    def _timeframe(value):
        mapping={"1m":("1 min",60),"5m":("5 mins",300),"15m":("15 mins",900),"1h":("1 hour",3600),"1d":("1 day",86400)}
        if value not in mapping:raise ValueError(f"Unsupported IBKR market-data timeframe {value}")
        return mapping[value]
    @staticmethod
    def _bar_time(bar):
        value=getattr(bar,"date",None) or getattr(bar,"time",None)
        if isinstance(value,date) and not isinstance(value,datetime):value=datetime.combine(value,time.min,tzinfo=timezone.utc)
        if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    def _market_payload(self,bar,payload,source,timeframe,seconds):
        start=self._bar_time(bar);end=start+timedelta(seconds=seconds)
        def field(primary,fallback=None):return getattr(bar,primary,getattr(bar,fallback,0) if fallback else 0)
        stable=f"{payload['conid']}:{timeframe}:{start.isoformat()}"
        return {"source_event_id":stable,"subscription_key":payload["subscription_key"],
            "instrument_id":int(payload["instrument_id"]),"conid":int(payload["conid"]),"symbol":payload["symbol"],
            "exchange":payload.get("exchange","SMART"),"currency":payload.get("currency","USD"),
            "event_kind":"BAR","timeframe":timeframe,"event_time":start.isoformat(),"window_start":start.isoformat(),
            "window_end":end.isoformat(),"open":str(field("open","open_")),"high":str(field("high","high")),
            "low":str(field("low","low")),"close":str(field("close","close")),
            "volume":str(max(0,field("volume","volume"))),"is_final":True,"source":source}
    def subscribe_market_data(self,payload):
        key=payload["subscription_key"]
        if key in self.market_subscriptions:return {"subscription_key":key,"state":"ACTIVE","historical_bar_count":0,"reused":True}
        qualified=self.ib.qualifyContracts(self._contract(payload))
        if not qualified:raise RuntimeError("Selected IBKR contract could not be qualified for market data")
        contract=qualified[0];self.contracts[str(contract.conId)]=contract
        bar_size,seconds=self._timeframe(payload["timeframe"]);count=max(1,int(payload.get("historical_bars",1)))
        days=max(1,(count*seconds+86399)//86400 + (2 if seconds>=86400 else 0))
        historical=self.ib.reqHistoricalData(contract,endDateTime="",durationStr=f"{days} D",barSizeSetting=bar_size,
            whatToShow=payload.get("what_to_show","TRADES"),useRTH=bool(payload.get("use_rth",False)),formatDate=2,keepUpToDate=False)
        if not historical:raise RuntimeError("IBKR historical request returned no bars; check contract and market-data permissions")
        for bar in list(historical)[-count:]:self.market_events.append(self._market_payload(bar,payload,"ibkr_historical",payload["timeframe"],seconds))
        live=self.ib.reqRealTimeBars(contract,5,payload.get("what_to_show","TRADES"),bool(payload.get("use_rth",False)))
        def on_update(bars,*_args):
            if bars:self.market_events.append(self._market_payload(bars[-1],payload,"ibkr_live","5s",5))
        live.updateEvent += on_update
        self.market_subscriptions[key]={"live":live,"handler":on_update,"payload":dict(payload)}
        return {"subscription_key":key,"state":"ACTIVE","historical_bar_count":min(len(historical),count),"conid":contract.conId}
    def cancel_market_data(self,payload):
        key=payload["subscription_key"];current=self.market_subscriptions.pop(key,None)
        if current:self.ib.cancelRealTimeBars(current["live"])
        return {"subscription_key":key,"state":"INACTIVE"}
    def drain_market_events(self):
        events=[]
        while self.market_events:events.append(self.market_events.popleft())
        return events
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
        order = self._order(payload); order.orderRef = payload["internal_id"]
        if payload.get("account"): order.account = payload["account"]
        trade = self.ib.placeOrder(contract, order); self.trades[payload["internal_id"]] = trade
        return {"internal_id":payload["internal_id"], "broker_order_id":str(trade.order.orderId), "permanent_id":str(trade.order.permId or ""), "status":trade.orderStatus.status}
    def _find_trade(self, internal_id):
        trade = self.trades.get(internal_id)
        if trade: return trade
        for candidate in self.ib.trades():
            if candidate.order.orderRef == internal_id:
                self.trades[internal_id] = candidate
                return candidate
        raise RuntimeError(f"Broker order not found for {internal_id}")
    def modify_order(self, payload):
        trade = self._find_trade(payload["internal_id"])
        for source, dest in [("quantity","totalQuantity"),("limit_price","lmtPrice"),("stop_price","auxPrice")]:
            if source in payload: setattr(trade.order, dest, float(payload[source]))
        trade = self.ib.placeOrder(trade.contract, trade.order); return {"broker_order_id":str(trade.order.orderId), "status":trade.orderStatus.status}
    def cancel_order(self, payload):
        trade = self._find_trade(payload["internal_id"]); self.ib.cancelOrder(trade.order); return {"broker_order_id":str(trade.order.orderId), "status":"PendingCancel"}
    def _trade_data(self, trade):
        order, status = trade.order, trade.orderStatus
        return {**self._contract_data(trade.contract),"account":order.account,"internal_id":order.orderRef,"broker_order_id":str(order.orderId),"permanent_id":str(order.permId or ""),"side":order.action,"quantity":str(order.totalQuantity),"order_type":order.orderType,"limit_price":None if order.lmtPrice in (0,1.7976931348623157e308) else str(order.lmtPrice),"stop_price":None if order.auxPrice in (0,1.7976931348623157e308) else str(order.auxPrice),"time_in_force":order.tif,"status":status.status,"filled_quantity":str(status.filled),"remaining_quantity":str(status.remaining),"average_fill_price":str(status.avgFillPrice or 0)}
    def refresh_state(self):
        summary=[]
        for value in self.ib.accountValues(): summary.append({"account":value.account,"tag":value.tag,"value":value.value,"currency":value.currency,"model_code":value.modelCode})
        portfolio_prices={p.contract.conId:p.marketPrice for account in self.ib.managedAccounts() for p in self.ib.portfolio(account)}
        positions=[{"account":p.account,**self._contract_data(p.contract),"quantity":str(p.position),"average_cost":str(p.avgCost),"market_price":str(portfolio_prices.get(p.contract.conId,0) or 0)} for p in self.ib.positions()]
        open_trades=self.ib.openTrades(); open_keys={(t.order.clientId,t.order.orderId) for t in open_trades}
        completed=[t for t in self.ib.trades() if (t.order.clientId,t.order.orderId) not in open_keys]
        executions=[]
        for fill in self.ib.fills():
            report=fill.commissionReport; execution=fill.execution
            commission=report.commission if report and report.commission < 1e100 else 0
            executions.append({"execution_id":execution.execId,"broker_order_id":str(execution.orderId),"permanent_id":str(execution.permId or ""),"account":execution.acctNumber,"side":execution.side,"quantity":str(execution.shares),"price":str(execution.price),"executed_at":execution.time.isoformat() if execution.time else None,"commission":str(commission),"currency":report.currency if report else fill.contract.currency,**self._contract_data(fill.contract)})
        return {"accounts":[{"account_id":account} for account in self.ib.managedAccounts()],"account_summary":summary,"positions":positions,"open_orders":[self._trade_data(t) for t in open_trades],"completed_orders":[self._trade_data(t) for t in completed],"executions":executions,"reconciled":True}
    def wait(self, seconds): self.ib.sleep(seconds)
