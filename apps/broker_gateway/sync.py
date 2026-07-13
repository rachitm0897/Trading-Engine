from decimal import Decimal, InvalidOperation
import hashlib
import json
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.accounts.models import BrokerAccount
from apps.audit.models import OutboxEvent
from apps.execution.models import Fill
from apps.instruments.models import BrokerContract, Instrument
from apps.oms.models import Order, OrderIntent, OrderStatusHistory
from apps.oms.services import ALLOWED, apply_execution
from apps.portfolios.models import PortfolioPosition, TradingPortfolio
from apps.market_streams.models import MarketDataSubscription
from apps.strategies.models import StrategyInstance
from .client import GatewayClient
from .models import BrokerSyncCursor

TERMINAL={"FILLED","CANCELLED","REJECTED","EXPIRED"}
STATUS_MAP={
    "PendingSubmit":"SUBMITTED","ApiPending":"SUBMITTED","PreSubmitted":"ACKNOWLEDGED",
    "Submitted":"ACKNOWLEDGED","PendingCancel":"CANCEL_PENDING","ApiCancelled":"CANCELLED",
    "Cancelled":"CANCELLED","Inactive":"REJECTED","ValidationError":"REJECTED","Filled":"FILLED",
    "Expired":"EXPIRED","Unknown":"UNKNOWN",
}

def dec(value, default="0"):
    try: return Decimal(str(value if value not in (None,"") else default).replace(",",""))
    except (InvalidOperation,ValueError): return Decimal(default)

def ensure_account(account_id):
    account,_=BrokerAccount.objects.get_or_create(account_id=account_id or "UNKNOWN",defaults={"alias":f"IBKR {account_id or 'UNKNOWN'}"})
    portfolio,_=TradingPortfolio.objects.get_or_create(account=account,name=f"IBKR {account.account_id}")
    return account,portfolio

def ensure_instrument(row):
    conid=int(row.get("conid") or 0)
    if conid:
        existing=BrokerContract.objects.select_related("instrument").filter(conid=conid).first()
        if existing:
            from apps.instruments.services import publish_instrument_registry
            publish_instrument_registry(existing);return existing.instrument
    symbol=row.get("symbol") or row.get("local_symbol") or (f"CONID-{conid}" if conid else "UNKNOWN")
    defaults={"asset_class":row.get("asset_class") or "STK","exchange":row.get("exchange") or row.get("primary_exchange") or "SMART",
        "primary_exchange":row.get("primary_exchange") or "","currency":row.get("currency") or "USD"}
    instrument=Instrument.objects.filter(symbol=symbol,asset_class=defaults["asset_class"],exchange=defaults["exchange"],
        currency=defaults["currency"],primary_exchange="",broker_contract__isnull=True).first()
    if instrument and defaults["primary_exchange"]:
        instrument.primary_exchange=defaults["primary_exchange"];instrument.save(update_fields=["primary_exchange"])
    if not instrument:instrument,_=Instrument.objects.get_or_create(symbol=symbol,**defaults)
    if conid:
        contract,_=BrokerContract.objects.get_or_create(instrument=instrument,defaults={"conid":conid,
        "primary_exchange":row.get("primary_exchange") or "","local_symbol":row.get("local_symbol") or symbol,
        "description":row.get("description") or "","qualified_at":timezone.now()})
        from apps.instruments.services import publish_instrument_registry
        publish_instrument_registry(contract)
    return instrument

def sync_accounts(rows):
    for row in rows:
        account_id=row if isinstance(row,str) else row.get("account_id") or row.get("account")
        if account_id: ensure_account(account_id)

def sync_account_summary(rows):
    grouped={}
    for row in rows:
        account_id=row.get("account"); tag=row.get("tag")
        if account_id and tag: grouped.setdefault(account_id,{})[tag]=row
    for account_id,values in grouped.items():
        account,_=ensure_account(account_id)
        def value(*tags):
            for tag in tags:
                if tag in values: return dec(values[tag].get("value"))
            return Decimal(0)
        base=values.get("NetLiquidation",{}).get("currency") or values.get("TotalCashValue",{}).get("currency") or account.base_currency
        account.base_currency=base if base and base != "BASE" else account.base_currency
        account.net_liquidation=value("NetLiquidation")
        account.available_cash=value("AvailableFunds","TotalCashValue","CashBalance")
        account.buying_power=value("BuyingPower")
        account.daily_pnl=value("DailyPnL","RealizedPnL")
        account.save(update_fields=["base_currency","net_liquidation","available_cash","buying_power","daily_pnl","updated_at"])

def sync_positions(rows):
    PortfolioPosition.objects.update(quantity=0,average_cost=0,market_price=0)
    for row in rows:
        _,portfolio=ensure_account(row.get("account")); instrument=ensure_instrument(row)
        PortfolioPosition.objects.update_or_create(portfolio=portfolio,instrument=instrument,defaults={"quantity":dec(row.get("quantity")),"average_cost":dec(row.get("average_cost")),"market_price":dec(row.get("market_price"))})

def _external_order(row, instrument, portfolio):
    identity=row.get("permanent_id") or row.get("broker_order_id")
    internal=(row.get("internal_id") or f"IBKR-{portfolio.account.account_id}-{identity}")[:64]
    intent,_=OrderIntent.objects.get_or_create(idempotency_key=f"broker-import:{portfolio.account.account_id}:{identity}",defaults={"portfolio":portfolio,"instrument":instrument,"side":"BUY" if row.get("side") in {"BUY","BOT"} else "SELL","quantity":dec(row.get("quantity")),"order_type":row.get("order_type") or "MKT","limit_price":row.get("limit_price"),"stop_price":row.get("stop_price"),"time_in_force":row.get("time_in_force") or "DAY"})
    order,created=Order.objects.get_or_create(intent=intent,defaults={"internal_id":internal,"quantity":intent.quantity,"status":"ACKNOWLEDGED","broker_order_id":str(row.get("broker_order_id") or ""),"broker_permanent_id":str(row.get("permanent_id") or "")})
    if created: OrderStatusHistory.objects.create(order=order,from_status="",to_status="ACKNOWLEDGED",source="broker_import",reason="Discovered at IBKR",event_key=f"broker-import:{portfolio.account.account_id}:{identity}:ack")
    return order

def _broker_reason(row):
    return str(row.get("error_message") or row.get("why_held") or row.get("warning_text") or "")[:255]

def _record_broker_status(order,row,event_key,source="ibkr",target_override=None):
    broker_status=str(row.get("broker_status") or row.get("status") or "")
    target=target_override or STATUS_MAP.get(broker_status)
    details={"error_message":str(row.get("error_message") or ""),"why_held":str(row.get("why_held") or ""),
        "warning_text":str(row.get("warning_text") or ""),"advanced_reject":row.get("advanced_reject"),
        "trade_log":row.get("trade_log") or [],"broker_order_id":str(row.get("broker_order_id") or ""),
        "permanent_id":str(row.get("permanent_id") or "")}
    occurred=parse_datetime(str(row.get("occurred_at") or "")) or timezone.now()
    history,_=OrderStatusHistory.objects.get_or_create(event_key=event_key[:128],defaults={"order":order,
        "from_status":order.status,"to_status":target or order.status,"source":source,"broker_status":broker_status,
        "reason_code":str(row.get("error_code") or "")[:64],"reason":_broker_reason(row),"details":details,
        "occurred_at":occurred,"operator_requested":bool(row.get("operator_requested"))})
    if target and target!="FILLED" and order.status not in TERMINAL and target in ALLOWED.get(order.status,set()):
        order.status=target;order.save(update_fields=["status","updated_at"])
    return history

def sync_orders(rows, snapshot):
    for row in rows:
        _,portfolio=ensure_account(row.get("account")); instrument=ensure_instrument(row)
        order=None
        if row.get("internal_id"): order=Order.objects.filter(internal_id=row["internal_id"]).first()
        if not order and row.get("permanent_id"): order=Order.objects.filter(broker_permanent_id=str(row["permanent_id"])).first()
        if not order and row.get("broker_order_id"): order=Order.objects.filter(broker_order_id=str(row["broker_order_id"])).first()
        order=order or _external_order(row,instrument,portfolio)
        order.broker_order_id=str(row.get("broker_order_id") or order.broker_order_id)
        order.broker_permanent_id=str(row.get("permanent_id") or order.broker_permanent_id)
        order.quantity=max(order.quantity,dec(row.get("quantity")))
        order.save(update_fields=["broker_order_id","broker_permanent_id","quantity","updated_at"])
        identity=json.dumps([snapshot,order.internal_id,row.get("status"),row.get("filled_quantity"),row.get("error_code"),
            row.get("error_message"),row.get("why_held"),row.get("occurred_at")],default=str,separators=(",",":"))
        _record_broker_status(order,row,f"broker-snapshot:{hashlib.sha256(identity.encode()).hexdigest()}")

def sync_order_event(row):
    order=None
    if row.get("internal_id"):order=Order.objects.filter(internal_id=row["internal_id"]).first()
    if not order and row.get("permanent_id"):order=Order.objects.filter(broker_permanent_id=str(row["permanent_id"])).first()
    if not order and row.get("broker_order_id"):order=Order.objects.filter(broker_order_id=str(row["broker_order_id"])).first()
    if not order:
        _,portfolio=ensure_account(row.get("account"));instrument=ensure_instrument(row)
        order=_external_order({**row,"status":row.get("broker_status")},instrument,portfolio)
    order.broker_order_id=str(row.get("broker_order_id") or order.broker_order_id)
    order.broker_permanent_id=str(row.get("permanent_id") or order.broker_permanent_id)
    order.save(update_fields=["broker_order_id","broker_permanent_id","updated_at"])
    source_id=str(row.get("source_event_id") or "")
    if not source_id:
        source_id=hashlib.sha256(json.dumps(row,sort_keys=True,default=str).encode()).hexdigest()
    return _record_broker_status(order,row,f"broker-order:{source_id}")

def record_gateway_command_failure(payload):
    command_payload=payload.get("payload") or {};internal_id=str(command_payload.get("internal_id") or "")
    order=Order.objects.filter(internal_id=internal_id).first()
    if not order:return
    command_type=str(payload.get("command_type") or "");target={"PLACE_ORDER":"BROKER_BLOCKED",
        "MODIFY_ORDER":"UNKNOWN","CANCEL_ORDER":"UNKNOWN"}.get(command_type)
    row={"broker_status":"GatewayCommandFailed","error_code":"GATEWAY_COMMAND_FAILED",
        "error_message":str(payload.get("error") or "Gateway order command failed"),
        "operator_requested":command_type=="CANCEL_ORDER","occurred_at":payload.get("occurred_at")}
    _record_broker_status(order,row,f"gateway-command:{payload.get('command_id')}:{command_type}",source="gateway",
        target_override=target)

def sync_executions(rows):
    for row in rows:
        if not row.get("execution_id") or Fill.objects.filter(execution_id=row["execution_id"]).exists(): continue
        _,portfolio=ensure_account(row.get("account")); instrument=ensure_instrument(row)
        order=None
        if row.get("permanent_id"): order=Order.objects.filter(broker_permanent_id=str(row["permanent_id"])).first()
        if not order and row.get("broker_order_id"): order=Order.objects.filter(broker_order_id=str(row["broker_order_id"])).first()
        if not order:
            synthetic={**row,"internal_id":"","quantity":row.get("quantity"),"order_type":"MKT","time_in_force":"DAY","status":"Submitted"}
            order=_external_order(synthetic,instrument,portfolio)
        if order.status in {"CREATED","RISK_APPROVED","QUEUED","BROKER_BLOCKED","SUBMITTED","UNKNOWN"}:
            OrderStatusHistory.objects.get_or_create(event_key=f"broker-execution-ready:{order.internal_id}",defaults={"order":order,"from_status":order.status,"to_status":"ACKNOWLEDGED","source":"broker_sync","reason":"Execution received from IBKR"})
            order.status="ACKNOWLEDGED"; order.quantity=max(order.quantity,order.filled_quantity+dec(row.get("quantity"))); order.save(update_fields=["status","quantity","updated_at"])
        executed_at=parse_datetime(row.get("executed_at") or "") or timezone.now()
        apply_execution(order,{**row,"quantity":str(dec(row.get("quantity"))),"price":str(dec(row.get("price"))),"commission":str(dec(row.get("commission"))),"executed_at":executed_at})

def process_snapshot(event):
    event_type=event.get("event_type","");payload=event.get("payload",{})
    if event_type=="command.qualify.completed":
        ensure_instrument(payload);return
    if event_type=="broker.order":
        sync_order_event(payload);return
    if event_type=="market.raw":
        source_key=str(payload.get("source_event_id") or "")
        if not source_key:return
        OutboxEvent.objects.get_or_create(idempotency_key=f"gateway-market:{source_key}",defaults={"topic":"market.raw.v1",
            "event_type":"market.raw","aggregate_type":"instrument","aggregate_id":str(payload["instrument_id"]),
            "partition_key":str(payload["instrument_id"]),"payload":payload})
        MarketDataSubscription.objects.filter(instrument_id=payload.get("instrument_id"),timeframe=payload.get("timeframe")).update(
            state="ACTIVE",last_event_at=parse_datetime(payload.get("event_time") or "") or timezone.now(),last_error="")
        return
    if event_type in {"command.subscribe_market_data.completed","command.cancel_market_data.completed"}:
        key=str(payload.get("subscription_key") or "")
        if ":" in key:
            instrument_id,timeframe=key.split(":",1)
            MarketDataSubscription.objects.filter(instrument_id=instrument_id,timeframe=timeframe).update(
                state="ACTIVE" if event_type=="command.subscribe_market_data.completed" else "INACTIVE",last_error="")
        return
    if event_type=="command.failed" and payload.get("command_type") in {"SUBSCRIBE_MARKET_DATA","CANCEL_MARKET_DATA"}:
        command_payload=payload.get("payload") or {};key=str(command_payload.get("subscription_key") or "")
        if ":" in key:
            instrument_id,timeframe=key.split(":",1);reason=str(payload.get("error") or "Gateway market-data command failed")[:2000]
            MarketDataSubscription.objects.filter(instrument_id=instrument_id,timeframe=timeframe).update(state="ERROR",last_error=reason)
            StrategyInstance.objects.filter(enabled=True,instrument_id=instrument_id,timeframe=timeframe).update(state="BLOCKED",block_reason=reason[:255])
        return
    if event_type=="command.failed" and payload.get("command_type") in {"PLACE_ORDER","MODIFY_ORDER","CANCEL_ORDER"}:
        record_gateway_command_failure(payload);return
    if event_type=="session.disconnected":
        reason=str(payload.get("error") or "IBKR connection lost")
        occurred=payload.get("occurred_at")
        for order in Order.objects.filter(status__in=["SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED","CANCEL_PENDING"]):
            _record_broker_status(order,{"broker_status":"Unknown","error_code":"CONNECTION_LOST",
                "error_message":reason,"occurred_at":occurred},f"broker-disconnect:{event.get('id')}:{order.internal_id}")
        return
    rows=payload.get("value",[])
    if event_type=="snapshot.accounts": sync_accounts(rows)
    elif event_type=="snapshot.account_summary": sync_account_summary(rows)
    elif event_type=="snapshot.positions": sync_positions(rows)
    elif event_type=="snapshot.open_orders": sync_orders(rows,"open")
    elif event_type=="snapshot.completed_orders": sync_orders(rows,"completed")
    elif event_type=="snapshot.executions": sync_executions(rows)

def sync_events(client=None):
    client=client or GatewayClient()
    with transaction.atomic():
        cursor,_=BrokerSyncCursor.objects.select_for_update().get_or_create(name="gateway-events")
        events=client.events(cursor.last_sequence) or []
        for event in events:
            process_snapshot(event); cursor.last_sequence=event["id"]
        cursor.last_synced_at=timezone.now(); cursor.last_error=""; cursor.save(update_fields=["last_sequence","last_synced_at","last_error"])
    if events: client.ack_events(cursor.last_sequence)
    return len(events)
