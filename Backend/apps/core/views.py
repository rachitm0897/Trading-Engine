from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
import json
import uuid

def response(data=None, *, status=200, error=None, meta=None):
    return JsonResponse({"ok": error is None, "data": data if error is None else None, "error": error, "meta": meta or {}}, status=status, safe=False)

def health(request):
    try:
        with connection.cursor() as cursor: cursor.execute("SELECT 1")
        return response({"status": "healthy", "database": "connected", "time": timezone.now().isoformat()})
    except Exception as exc:
        return response(status=503, error={"code": "DATABASE_UNAVAILABLE", "message": str(exc), "details": {}})

def system(request):
    from apps.reconciliation.models import ReconciliationBreak
    from apps.risk.models import KillSwitch
    return response({"mode": "PAPER" if not settings.ALLOW_LIVE_TRADING else "LIVE", "global_kill_switch": settings.GLOBAL_KILL_SWITCH or KillSwitch.objects.filter(scope="GLOBAL", enabled=True).exists(), "material_breaks": ReconciliationBreak.objects.filter(material=True, resolved=False).count(), "time": timezone.now().isoformat()})

def _serialize(queryset, fields):
    rows = []
    for obj in queryset:
        row = {field: getattr(obj, field) for field in fields}
        row["id"] = obj.pk
        rows.append(row)
    return rows

def _page(request, default=250, maximum=500):
    try:
        limit = min(max(int(request.GET.get("limit", default)), 1), maximum)
        offset = max(int(request.GET.get("offset", 0)), 0)
    except (TypeError, ValueError):
        limit, offset = default, 0
    return limit, offset

@csrf_exempt
def gateway(request):
    from apps.broker_gateway.client import GatewayClient, GatewayError
    try:
        if request.method == "POST": return response(GatewayClient().request("POST", "session/reconnect/", retries=0))
        return response(GatewayClient().health())
    except GatewayError as exc: return response(status=503, error={"code":"GATEWAY_UNAVAILABLE", "message":str(exc), "details":{}})

def accounts(request):
    from apps.accounts.models import BrokerAccount
    return response(_serialize(BrokerAccount.objects.all(), ["account_id", "alias", "base_currency", "net_liquidation", "available_cash", "buying_power", "daily_pnl", "is_reconciled", "kill_switch", "updated_at"]))

def instruments(request):
    from apps.instruments.models import Instrument
    return response(_serialize(Instrument.objects.all(), ["symbol", "asset_class", "exchange", "currency", "sector", "multiplier", "lot_size", "min_tick", "fractional_support", "trading_calendar", "active", "tradable"]))

def portfolios(request):
    from apps.portfolios.models import TradingPortfolio
    rows=[]
    for item in TradingPortfolio.objects.select_related("account"):
        rows.append({"id":item.pk,"name":item.name,"account_id":item.account_id,"account":item.account.account_id,
            "cash_buffer_pct":item.cash_buffer_pct,"margin_buffer_pct":item.margin_buffer_pct,
            "minimum_notional":item.minimum_notional,"minimum_quantity":item.minimum_quantity,
            "minimum_drift":item.minimum_drift,"kill_switch":item.kill_switch})
    return response(rows)

def positions(request):
    from apps.portfolios.models import PortfolioPosition
    rows=[]
    query=PortfolioPosition.objects.select_related("instrument","portfolio__account")
    if request.GET.get("portfolio"):query=query.filter(portfolio_id=request.GET["portfolio"])
    if request.GET.get("symbol"):query=query.filter(instrument__symbol__iexact=request.GET["symbol"])
    for item in query:
        rows.append({"id":item.pk,"portfolio_id":item.portfolio_id,"portfolio":item.portfolio.name,"account_id":item.portfolio.account.account_id,"instrument_id":item.instrument_id,"symbol":item.instrument.symbol,"asset_class":item.instrument.asset_class,"currency":item.instrument.currency,"quantity":item.quantity,"average_cost":item.average_cost,"market_price":item.market_price,"market_value":item.quantity*item.market_price,"updated_at":item.updated_at})
    return response(rows)

@csrf_exempt
def strategies(request):
    from apps.strategies.models import TradingStrategy
    return response(_serialize(TradingStrategy.objects.all(), ["name", "strategy_type", "version", "enabled", "schedule", "configuration", "allocated_capital", "maximum_target_weight", "kill_switch"]))

@csrf_exempt
def strategy_runs(request):
    from apps.strategies.models import StrategyRun, TradingStrategy
    from apps.strategies.services import run_strategy
    if request.method == "POST":
        try:
            payload = json.loads(request.body or b"{}")
            run = run_strategy(TradingStrategy.objects.get(pk=payload["strategy_id"]))
            return response({"id": run.pk, "status": run.status}, status=201)
        except (KeyError, ValueError, TradingStrategy.DoesNotExist) as exc: return response(status=400, error={"code":"INVALID_STRATEGY_RUN", "message":str(exc), "details":{}})
    return response(_serialize(StrategyRun.objects.all().order_by("-started_at")[:100], ["strategy_id", "input_hash", "status", "started_at", "completed_at"]))

def rebalances(request):
    from apps.allocation.models import RebalanceRun
    return response(_serialize(RebalanceRun.objects.all().order_by("-created_at")[:100], ["portfolio_id", "trigger", "idempotency_key", "status", "created_at"]))

@csrf_exempt
def orders(request, internal_id=None, action=None):
    from decimal import Decimal, InvalidOperation
    from django.db import transaction
    from apps.broker_gateway.client import GatewayClient, GatewayError
    from apps.instruments.models import Instrument
    from apps.oms.models import Order, OrderIntent
    from apps.oms.services import create_order, transition
    from apps.portfolios.models import TradingPortfolio
    from apps.risk.services import evaluate_intent
    if request.method == "GET":
        limit,offset=_page(request)
        query=Order.objects.select_related("intent__instrument","intent__portfolio__account").order_by("-created_at")
        if request.GET.get("portfolio"):query=query.filter(intent__portfolio_id=request.GET["portfolio"])
        if request.GET.get("status"):query=query.filter(status=request.GET["status"].upper())
        if request.GET.get("symbol"):query=query.filter(intent__instrument__symbol__iexact=request.GET["symbol"])
        total=query.count()
        rows=[]
        for order in query[offset:offset+limit]:
            rows.append({"id":order.pk,"internal_id":order.internal_id,"account_id":order.intent.portfolio.account.account_id,
                "portfolio_id":order.intent.portfolio_id,"symbol":order.intent.instrument.symbol,"side":order.intent.side,
                "order_type":order.intent.order_type,"time_in_force":order.intent.time_in_force,"broker_order_id":order.broker_order_id,
                "broker_permanent_id":order.broker_permanent_id,"status":order.status,"quantity":order.quantity,
                "filled_quantity":order.filled_quantity,"average_fill_price":order.average_fill_price,
                "created_at":order.created_at,"updated_at":order.updated_at})
        return response(rows,meta={"count":total,"limit":limit,"offset":offset})
    key=request.headers.get("Idempotency-Key")
    if not key: return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    try:
        if not internal_id:
            payload=json.loads(request.body or b"{}")
            side=payload.get("side","").upper(); order_type=payload.get("order_type","MKT").upper(); tif=payload.get("time_in_force","DAY").upper()
            quantity=Decimal(str(payload["quantity"])); reference=Decimal(str(payload.get("reference_price") or payload.get("limit_price") or 0))
            if side not in {"BUY","SELL"} or order_type not in {"MKT","LMT","STP","STP_LMT"} or tif not in {"DAY","GTC"} or quantity<=0: raise ValueError("Invalid side, order type, time in force, or quantity")
            portfolio=TradingPortfolio.objects.select_related("account").get(pk=payload["portfolio_id"]); instrument=Instrument.objects.get(pk=payload["instrument_id"])
            with transaction.atomic():
                intent,_=OrderIntent.objects.get_or_create(idempotency_key=key,defaults={"portfolio":portfolio,"instrument":instrument,"side":side,"quantity":quantity,"order_type":order_type,"limit_price":payload.get("limit_price"),"stop_price":payload.get("stop_price"),"reference_price":reference or None,"time_in_force":tif})
                if hasattr(intent,"order"): return response({"internal_id":intent.order.internal_id,"status":intent.order.status},status=200)
                gateway=GatewayClient(); state=gateway.health()
                decision,approved,_=evaluate_intent(intent,{"max_quantity":payload.get("max_quantity",quantity),"max_notional":payload.get("max_notional","100000")},state)
                if decision not in {"APPROVED","RESIZED"}: return response(status=422,error={"code":f"RISK_{decision}","message":"Order did not pass pre-trade risk","details":{"decision":decision}})
                order=create_order(intent,approved); order=transition(order,"QUEUED","oms",f"order:{order.internal_id}:queued")
                command=gateway.place_order({"internal_id":order.internal_id,"account":portfolio.account.account_id,"symbol":instrument.symbol,"asset_class":instrument.asset_class,"exchange":instrument.exchange,"currency":instrument.currency,"side":side,"quantity":str(approved),"order_type":order_type,"limit_price":str(intent.limit_price) if intent.limit_price else None,"stop_price":str(intent.stop_price) if intent.stop_price else None,"time_in_force":tif},f"gateway:place:{order.internal_id}")
                return response({"internal_id":order.internal_id,"status":order.status,"decision":decision,"approved_quantity":approved,"gateway_command":command},status=201)
        order=Order.objects.select_related("intent").get(internal_id=internal_id); gateway=GatewayClient()
        if action=="cancel":
            if order.status not in {"QUEUED","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED","UNKNOWN"}: raise ValueError("Order cannot be cancelled in its current state")
            order=transition(order,"CANCEL_PENDING","operator",f"order:{order.internal_id}:cancel:{key}")
            command=gateway.cancel_order(order.internal_id,key); return response({"internal_id":order.internal_id,"status":order.status,"gateway_command":command},status=202)
        payload=json.loads(request.body or b"{}")
        if order.status not in {"QUEUED","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED"}: raise ValueError("Order cannot be modified in its current state")
        allowed={k:v for k,v in payload.items() if k in {"quantity","limit_price","stop_price","time_in_force"}}
        if not allowed: raise ValueError("No modifiable fields supplied")
        command=gateway.modify_order(order.internal_id,allowed,key); return response({"internal_id":order.internal_id,"status":order.status,"gateway_command":command},status=202)
    except (KeyError,ValueError,InvalidOperation,TradingPortfolio.DoesNotExist,Instrument.DoesNotExist,Order.DoesNotExist) as exc:
        return response(status=400,error={"code":"INVALID_ORDER","message":str(exc),"details":{}})
    except GatewayError as exc:
        return response(status=503,error={"code":"GATEWAY_UNAVAILABLE","message":str(exc),"details":{}})

def executions(request):
    from apps.execution.models import Fill
    limit,offset=_page(request)
    query=Fill.objects.select_related("order__intent__instrument","order__intent__portfolio__account").order_by("-executed_at")
    if request.GET.get("portfolio"):query=query.filter(order__intent__portfolio_id=request.GET["portfolio"])
    if request.GET.get("symbol"):query=query.filter(order__intent__instrument__symbol__iexact=request.GET["symbol"])
    total=query.count()
    rows=[]
    for fill in query[offset:offset+limit]:
        rows.append({"id":fill.pk,"order_id":fill.order.internal_id,"account_id":fill.order.intent.portfolio.account.account_id,"symbol":fill.order.intent.instrument.symbol,"execution_id":fill.execution_id,"quantity":fill.quantity,"price":fill.price,"commission":fill.commission,"currency":fill.currency,"executed_at":fill.executed_at})
    return response(rows,meta={"count":total,"limit":limit,"offset":offset})

def reconciliation(request):
    from apps.reconciliation.models import ReconciliationRun, ReconciliationBreak
    limit,_=_page(request,100)
    runs=ReconciliationRun.objects.all().order_by("-started_at")
    breaks=ReconciliationBreak.objects.filter(resolved=False).order_by("-created_at")
    if request.GET.get("status"):runs=runs.filter(status=request.GET["status"].upper())
    if request.GET.get("category"):breaks=breaks.filter(category=request.GET["category"])
    if request.GET.get("severity"):breaks=breaks.filter(severity=request.GET["severity"].upper())
    return response({"runs": _serialize(runs[:limit], ["trigger", "status", "started_at", "completed_at"]),
        "breaks": _serialize(breaks[:limit], ["run_id", "category", "severity", "internal_value", "broker_value", "material", "resolved", "resolution", "created_at"])})

@csrf_exempt
def risk(request):
    from apps.risk.models import KillSwitch, RiskCheckResult
    if request.method == "POST":
        payload = json.loads(request.body or b"{}")
        switch, _ = KillSwitch.objects.update_or_create(scope=payload.get("scope", "GLOBAL"), scope_id=str(payload.get("scope_id", "")), defaults={"enabled": bool(payload.get("enabled", True)), "reason": payload.get("reason", "Operator action")})
        return response({"id": switch.pk, "enabled": switch.enabled})
    return response({"kill_switches": _serialize(KillSwitch.objects.all(), ["scope", "scope_id", "enabled", "reason", "updated_at"]), "decisions": _serialize(RiskCheckResult.objects.all().order_by("-created_at")[:250], ["order_intent_id", "check_name", "decision", "reason", "requested_quantity", "approved_quantity", "created_at"])})

def audit(request):
    from apps.audit.models import AuditEvent
    limit,offset=_page(request)
    query=AuditEvent.objects.all().order_by("-created_at")
    if request.GET.get("event_type"):query=query.filter(event_type=request.GET["event_type"])
    if request.GET.get("actor"):query=query.filter(actor=request.GET["actor"])
    total=query.count()
    return response(_serialize(query[offset:offset+limit], ["event_type", "actor", "aggregate_type", "aggregate_id", "data", "created_at"]),
        meta={"count":total,"limit":limit,"offset":offset})
