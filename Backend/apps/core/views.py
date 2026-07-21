from django.conf import settings
from django.db import connection
from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.csrf import ensure_csrf_cookie
import json
import hashlib
import uuid
from apps.core.idempotency import IdempotencyConflict
from apps.broker_gateway.configuration import managed_broker_deployment_configuration

def response(data=None, *, status=200, error=None, meta=None):
    return JsonResponse({"ok": error is None, "data": data if error is None else None, "error": error, "meta": meta or {}}, status=status, safe=False)

def method_guard(request, *allowed):
    if request.method not in allowed:
        return response(status=405,error={"code":"METHOD_NOT_ALLOWED",
            "message":f"{' or '.join(allowed)} required","details":{}})
    return None

def health(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    return response({"status": "healthy", "process": "running", "time": timezone.now().isoformat()})


def dashboard_alias(request):
    invalid = method_guard(request, "GET")
    if invalid:
        return invalid
    return HttpResponseRedirect(f"{settings.APP_BASE_PATH}/api/v1/dashboard/summary/")


def readiness(request):
    """Check required Backend readiness and report optional broker deployment status."""
    invalid = method_guard(request, "GET")
    if invalid:
        return invalid
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        deployment = managed_broker_deployment_configuration()
        if not settings.RECOMMENDATION_SYSTEM_ENABLED:
            return response({"status": "ready", "recommendation_system": "disabled", "deployment": deployment})
        from apps.portfolio_construction.rules import MAXIMUM_RISK
        from apps.research.models import BacktestProtocolVersion, RecommendationCacheSnapshot
        from apps.research.services.strategy_registry import REGISTRY
        from apps.research.services.universe_pipeline import active_recommendation_universe

        universe = active_recommendation_universe(require_complete=True)
        protocol = BacktestProtocolVersion.objects.get(dataset_version=universe.dataset_version, active=True)
        expected = {
            (timeframe, risk_level)
            for timeframe, maximum_risk in MAXIMUM_RISK.items()
            for risk_level in range(1, maximum_risk + 1)
        }
        current = set(RecommendationCacheSnapshot.objects.filter(
            dataset_version=universe.dataset_version, protocol_version=protocol,
            status="COMPLETED", expires_at__gt=timezone.now(),
        ).values_list("goal_timeframe", "risk_level"))
        missing = sorted(expected - current)
        details = {
            "deployment": deployment,
            "universe_members": universe.members.filter(active=True, membership_end__isnull=True).count(),
            "strategy_implementations": len(REGISTRY), "current_cache_profiles": len(expected & current),
            "required_cache_profiles": len(expected), "missing_cache_profiles": [f"{key}:{risk}" for key, risk in missing],
        }
        if len(REGISTRY) != 97 or missing:
            return response(status=503, error={
                "code": "RECOMMENDATION_SYSTEM_NOT_READY",
                "message": "Bootstrap and cache warming must complete before recommendation traffic is enabled",
                "details": details,
            })
        return response({"status": "ready", "deployment": deployment, **details})
    except Exception as exc:
        return response(status=503, error={
            "code": "RECOMMENDATION_SYSTEM_NOT_READY", "message": str(exc),
            "details": {"deployment": managed_broker_deployment_configuration()},
        })

@ensure_csrf_cookie
def system(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    from apps.reconciliation.models import ReconciliationBreak
    from apps.risk.models import KillSwitch
    is_admin = bool(getattr(request, "user", None) and request.user.is_authenticated and request.user.is_active and request.user.is_staff)
    return response({"mode":"MULTI_SESSION","execution_mode":settings.NEW_EXECUTION_MODE,
        "allow_live_trading":settings.ALLOW_LIVE_TRADING,
        "broker_deployment":managed_broker_deployment_configuration(),
        "is_admin":is_admin,"global_kill_switch": settings.GLOBAL_KILL_SWITCH or KillSwitch.objects.filter(scope="GLOBAL", enabled=True).exists(),
        "material_breaks": ReconciliationBreak.objects.filter(material=True, resolved=False).count(), "time": timezone.now().isoformat()})


@ensure_csrf_cookie
def auth_session(request):
    from django.contrib.auth import authenticate, login, logout
    user = getattr(request, "user", None)
    if request.method == "GET":
        return response({"is_authenticated": bool(user and user.is_authenticated),
            "is_admin": bool(user and user.is_authenticated and user.is_active and user.is_staff),
            "username": user.get_username() if user and user.is_authenticated else ""})
    if request.method == "DELETE":
        logout(request)
        return response({"is_authenticated": False, "is_admin": False, "username": ""})
    if request.method != "POST":
        return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"GET, POST, or DELETE required","details":{}})
    try:
        payload = json.loads(request.body or b"{}")
        authenticated = authenticate(request, username=str(payload.get("username") or ""), password=str(payload.get("password") or ""))
        if not authenticated:
            return response(status=401,error={"code":"AUTHENTICATION_FAILED","message":"Invalid administrator credentials","details":{}})
        if not authenticated.is_active or not authenticated.is_staff:
            return response(status=403,error={"code":"ADMIN_REQUIRED","message":"A staff administrator account is required","details":{}})
        login(request, authenticated)
        return response({"is_authenticated": True, "is_admin": True, "username": authenticated.get_username()})
    except json.JSONDecodeError:
        return response(status=400,error={"code":"INVALID_AUTH_REQUEST","message":"Request body must be valid JSON","details":{}})

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

def _order_row(order):
    return {"id":order.pk,"internal_id":order.internal_id,"account_id":order.intent.portfolio.account.account_id,
        "portfolio_id":order.intent.portfolio_id,"symbol":order.intent.instrument.symbol,"side":order.intent.side,
        "order_type":order.intent.order_type,"time_in_force":order.intent.time_in_force,"broker_order_id":order.broker_order_id,
        "broker_permanent_id":order.broker_permanent_id,"status":order.status,"quantity":order.quantity,
        "filled_quantity":order.filled_quantity,"average_fill_price":order.average_fill_price,
        "created_at":order.created_at,"updated_at":order.updated_at}

@csrf_exempt
def gateway(request):
    from apps.broker_gateway.client import GatewayClient, GatewayError
    from apps.broker_gateway.models import BrokerGatewaySession
    invalid=method_guard(request,"GET","POST")
    if invalid:return invalid
    try:
        if request.method == "POST":
            payload=json.loads(request.body or b"{}")
            session=BrokerGatewaySession.objects.get(pk=payload.get("session_id"))
            return response(GatewayClient(session,purpose="reconnect").reconnect())
        sessions=BrokerGatewaySession.objects.exclude(status__in=[BrokerGatewaySession.Status.STOPPING,
            BrokerGatewaySession.Status.DELETED]).order_by("created_at")
        rows=[{"id":str(item.pk),"mode":item.mode,"status":item.status,
            "connected":item.status==item.Status.CONNECTED,"reconciled":bool(item.last_gateway_state.get("reconciled")),
            "last_callback":item.last_gateway_state.get("last_callback")} for item in sessions]
        connected_rows=[item for item in rows if item["connected"]]
        return response({"connected":bool(connected_rows),"reconciled":bool(connected_rows) and all(
            item["reconciled"] for item in connected_rows),"mode":"multi-session","sessions":rows})
    except (BrokerGatewaySession.DoesNotExist,ValueError,TypeError) as exc:
        return response(status=400,error={"code":"BROKER_SESSION_REQUIRED","message":str(exc) or "A valid session_id is required","details":{}})
    except GatewayError as exc: return response(status=503, error={"code":"GATEWAY_UNAVAILABLE", "message":str(exc), "details":{}})

def accounts(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    from apps.accounts.models import BrokerAccount
    query=BrokerAccount.objects.all()
    if request.GET.get("session"):query=query.filter(gateway_sessions__session_id=request.GET["session"],gateway_sessions__available=True)
    return response(_serialize(query.distinct(), ["account_id", "alias", "base_currency", "net_liquidation", "available_cash", "buying_power", "daily_pnl", "is_reconciled", "kill_switch", "updated_at"]))

def instruments(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    from apps.instruments.models import Instrument
    return response(_serialize(Instrument.objects.all(), ["symbol", "asset_class", "exchange", "primary_exchange", "currency", "sector", "multiplier", "lot_size", "min_tick", "fractional_support", "trading_calendar", "active", "tradable"]))

def portfolios(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    from apps.portfolios.models import TradingPortfolio
    rows=[]
    for item in TradingPortfolio.objects.select_related("account"):
        rows.append({"id":item.pk,"name":item.name,"account_id":item.account_id,"account":item.account.account_id,
            "gateway_session_id":str(item.gateway_session_id) if item.gateway_session_id else None,
            "cash_buffer_pct":item.cash_buffer_pct,"margin_buffer_pct":item.margin_buffer_pct,
            "minimum_notional":item.minimum_notional,"minimum_quantity":item.minimum_quantity,
            "minimum_drift":item.minimum_drift,"kill_switch":item.kill_switch})
    return response(rows)

def positions(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    from apps.portfolios.models import PortfolioPosition
    rows=[]
    query=PortfolioPosition.objects.select_related("instrument__market_state","portfolio__account")
    if request.GET.get("portfolio"):query=query.filter(portfolio_id=request.GET["portfolio"])
    if request.GET.get("symbol"):query=query.filter(instrument__symbol__iexact=request.GET["symbol"])
    for item in query:
        from apps.market_data.pricing import effective_position_price
        price,provider,source=effective_position_price(item)
        rows.append({"id":item.pk,"portfolio_id":item.portfolio_id,"portfolio":item.portfolio.name,"account_id":item.portfolio.account.account_id,"instrument_id":item.instrument_id,"symbol":item.instrument.symbol,"asset_class":item.instrument.asset_class,"currency":item.instrument.currency,"quantity":item.quantity,"average_cost":item.average_cost,"market_price":price,"broker_market_price":item.market_price,"market_price_provider":provider,"market_price_source":source,"market_value":item.quantity*price,"updated_at":item.updated_at})
    return response(rows)

def rebalances(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
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
    from apps.core.validation import decimal_field, validate_order_payload
    if request.method == "GET":
        if internal_id and action=="detail":
            try:
                order=Order.objects.select_related("intent__instrument","intent__portfolio__account",
                    "intent__strategy_instance","intent__strategy_version").get(internal_id=internal_id)
            except Order.DoesNotExist:
                return response(status=404,error={"code":"ORDER_NOT_FOUND","message":"Order was not found","details":{}})
            history=[]
            for item in order.status_history.all().order_by("occurred_at","id"):
                history.append({"id":item.pk,"from_status":item.from_status,"to_status":item.to_status,
                    "broker_status":item.broker_status,"reason_code":item.reason_code,"reason":item.reason,
                    "source":item.source,"details":item.details,"occurred_at":item.occurred_at,
                    "operator_requested":item.operator_requested})
            fills=[{"execution_id":item.execution_id,"quantity":item.quantity,"price":item.price,
                "commission":item.commission,"currency":item.currency,"executed_at":item.executed_at,
                "raw_event":item.raw_event} for item in order.fills.all().order_by("executed_at","id")]
            risks=[{"id":item.pk,"check_name":item.check_name,"decision":item.decision,"reason":item.reason,
                "requested_quantity":item.requested_quantity,"approved_quantity":item.approved_quantity,
                "details":item.details,"created_at":item.created_at}
                for item in order.intent.risk_checks.all().order_by("created_at","id")]
            attributions=[{"id":item.pk,
                "strategy_id":item.strategy_instance_id or item.strategy_snapshot.get("strategy_instance_id") or item.strategy_snapshot.get("legacy_strategy_id"),
                "strategy":item.strategy_instance.name if item.strategy_instance else item.strategy_snapshot.get("strategy_name"),
                "strategy_instance_id":item.strategy_instance_id or item.strategy_snapshot.get("strategy_instance_id"),
                "strategy_instance":item.strategy_instance.name if item.strategy_instance else item.strategy_snapshot.get("strategy_instance_name"),
                "strategy_version_id":item.strategy_version_id or item.strategy_snapshot.get("strategy_version_id"),"target_delta":item.target_delta,
                "allocated_quantity":item.allocated_quantity,"allocated_value":item.allocated_value,
                "allocated_cost":item.allocated_cost,"realized_pnl":item.realized_pnl,"method":item.method}
                for item in order.intent.attributions.select_related("strategy_instance","strategy_version").all()]
            diagnostics=[item for item in history if item["broker_status"] or item["reason_code"] or item["source"] in {"ibkr","gateway"}]
            return response({"order":_order_row(order),"status_history":history,"broker_diagnostics":diagnostics,
                "risk_decisions":risks,"fills":fills,"strategy_attribution":attributions})
        limit,offset=_page(request)
        query=Order.objects.select_related("intent__instrument","intent__portfolio__account").order_by("-created_at")
        if request.GET.get("portfolio"):query=query.filter(intent__portfolio_id=request.GET["portfolio"])
        if request.GET.get("status"):query=query.filter(status=request.GET["status"].upper())
        if request.GET.get("symbol"):query=query.filter(intent__instrument__symbol__iexact=request.GET["symbol"])
        total=query.count()
        rows=[]
        for order in query[offset:offset+limit]:
            rows.append(_order_row(order))
        return response(rows,meta={"count":total,"limit":limit,"offset":offset})
    if not internal_id and request.method!="POST":
        return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"POST required","details":{}})
    if internal_id and action=="cancel" and request.method!="POST":
        return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"POST required","details":{}})
    if internal_id and action!="cancel" and request.method!="PATCH":
        return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"PATCH required","details":{}})
    key=request.headers.get("Idempotency-Key")
    if not key: return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    try:
        if not internal_id:
            payload=json.loads(request.body or b"{}")
            validated=validate_order_payload(payload)
            side=validated["side"];order_type=validated["order_type"];tif=validated["time_in_force"]
            quantity=validated["quantity"];reference=validated["reference_price"] or validated["limit_price"] or validated["stop_price"]
            portfolio=TradingPortfolio.objects.select_related("account","gateway_session").get(pk=payload["portfolio_id"]); instrument=Instrument.objects.get(pk=payload["instrument_id"])
            if not instrument.active or not instrument.tradable:raise ValueError("Instrument must be active and tradable")
            from apps.core.idempotency import canonical_request_hash, require_matching_request
            request_hash=canonical_request_hash("manual_order",payload)
            route_id=str(portfolio.gateway_session_id) if portfolio.gateway_session_id else "static-development"
            intent_key=f"manual:{route_id}:{hashlib.sha256(key.encode('utf-8')).hexdigest()}"
            retry_requested=request.headers.get("Idempotency-Retry","").strip().lower() in {"1","true","yes"}
            with transaction.atomic():
                from apps.audit.models import OperationAttempt
                intent,created=OrderIntent.objects.select_for_update().get_or_create(idempotency_key=intent_key,defaults={
                    "request_hash":request_hash,
                    "portfolio":portfolio,"instrument":instrument,"side":side,"quantity":quantity,"order_type":order_type,
                    "limit_price":validated["limit_price"],"stop_price":validated["stop_price"],
                    "reference_price":reference or None,"time_in_force":tif,
                    "mode":portfolio.gateway_session.mode.upper() if portfolio.gateway_session else "PAPER"})
                if created:
                    OperationAttempt.objects.create(operation_type="MANUAL_ORDER",operation_id=str(intent.pk),
                        attempt_number=intent.attempt_count,request_hash=intent.request_hash)
                else:
                    require_matching_request(intent.request_hash,request_hash)
                    if not intent.request_hash:
                        intent.request_hash=request_hash;intent.save(update_fields=["request_hash"])
                    if intent.operation_status=="FAILED":
                        if not retry_requested or not intent.retryable:
                            return response(status=503,error={"code":"STORED_ORDER_FAILURE",
                                "message":intent.operation_error or "Order operation failed","details":{"retryable":intent.retryable}})
                        intent.operation_status="PENDING";intent.operation_error="";intent.retryable=False
                        intent.attempt_count+=1;intent.save(update_fields=["operation_status","operation_error","retryable","attempt_count"])
                        OperationAttempt.objects.create(operation_type="MANUAL_ORDER",operation_id=str(intent.pk),
                            attempt_number=intent.attempt_count,request_hash=intent.request_hash)
                    elif hasattr(intent,"order"):
                        return response({"internal_id":intent.order.internal_id,"status":intent.order.status},status=200)
                    elif intent.operation_status=="RISK_REJECTED":
                        return response(status=422,error={"code":"RISK_REJECTED","message":intent.operation_error,
                            "details":{"decision":"REJECTED"}})
                    elif intent.operation_status=="PENDING":
                        return response({"intent_id":intent.pk,"status":"PENDING"},status=202)
            try:
                gateway=GatewayClient.for_portfolio(portfolio,require_commands=True)
                state=gateway.health()
            except GatewayError as exc:
                OrderIntent.objects.filter(pk=intent.pk).update(operation_status="FAILED",operation_error=str(exc)[:1000],retryable=True)
                OperationAttempt.objects.filter(operation_type="MANUAL_ORDER",operation_id=str(intent.pk),
                    attempt_number=intent.attempt_count).update(status="FAILED",retryable=True,error=str(exc)[:1000],completed_at=timezone.now())
                raise
            with transaction.atomic():
                intent=OrderIntent.objects.select_for_update().get(pk=intent.pk)
                decision,approved,_=evaluate_intent(intent,state)
                if decision not in {"APPROVED","RESIZED"}:
                    intent.operation_status="RISK_REJECTED";intent.operation_error="Order did not pass pre-trade risk"
                    intent.retryable=False;intent.save(update_fields=["operation_status","operation_error","retryable"])
                    OperationAttempt.objects.filter(operation_type="MANUAL_ORDER",operation_id=str(intent.pk),
                        attempt_number=intent.attempt_count).update(status="FAILED",retryable=False,error=intent.operation_error,
                        completed_at=timezone.now())
                    risk_rejected=True;order=None
                else:
                    risk_rejected=False
                    order=create_order(intent,approved);order=transition(order,"QUEUED","oms",f"order:{order.internal_id}:queued")
                    intent.operation_status="SUBMITTING";intent.save(update_fields=["operation_status"])
            if risk_rejected:
                return response(status=422,error={"code":f"RISK_{decision}","message":"Order did not pass pre-trade risk","details":{"decision":decision}})
            gateway_payload={"internal_id":order.internal_id,"account":portfolio.account.account_id,
                "symbol":instrument.symbol,"asset_class":instrument.asset_class,"exchange":instrument.exchange,
                "currency":instrument.currency,"side":side,"quantity":str(approved),"order_type":order_type,
                "limit_price":str(intent.limit_price) if intent.limit_price else None,
                "stop_price":str(intent.stop_price) if intent.stop_price else None,"time_in_force":tif}
            try:
                command=gateway.place_order(gateway_payload,f"gateway:place:{order.internal_id}")
            except GatewayError as exc:
                OrderIntent.objects.filter(pk=intent.pk).update(operation_status="FAILED",operation_error=str(exc)[:1000],retryable=True)
                OperationAttempt.objects.filter(operation_type="MANUAL_ORDER",operation_id=str(intent.pk),
                    attempt_number=intent.attempt_count).update(status="FAILED",retryable=True,error=str(exc)[:1000],completed_at=timezone.now())
                raise
            OrderIntent.objects.filter(pk=intent.pk).update(operation_status="QUEUED",operation_error="",retryable=False)
            OperationAttempt.objects.filter(operation_type="MANUAL_ORDER",operation_id=str(intent.pk),
                attempt_number=intent.attempt_count).update(status="COMPLETED",result={"order_id":order.internal_id,
                "gateway_command_id":command.get("command_id")},completed_at=timezone.now())
            return response({"internal_id":order.internal_id,"status":order.status,"decision":decision,
                "approved_quantity":approved,"gateway_command":command},status=201)
        order=Order.objects.select_related("intent__portfolio__account","intent__portfolio__gateway_session").get(internal_id=internal_id)
        if action=="cancel":
            if order.status not in {"QUEUED","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED","UNKNOWN"}: raise ValueError("Order cannot be cancelled in its current state")
            payload=json.loads(request.body or b"{}");operator_reason=str(payload.get("reason") or "")[:255]
            order=transition(order,"CANCEL_PENDING","operator",f"order:{order.internal_id}:cancel:{key}",operator_reason,
                reason_code="OPERATOR_CANCEL_REQUEST",details={"operator_reason":operator_reason},operator_requested=True)
            gateway=GatewayClient.for_order(order,require_commands=True)
            command=gateway.cancel_order(order.internal_id,key); return response({"internal_id":order.internal_id,"status":order.status,"gateway_command":command},status=202)
        payload=json.loads(request.body or b"{}")
        if order.status not in {"QUEUED","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED"}: raise ValueError("Order cannot be modified in its current state")
        permitted={"quantity","limit_price","stop_price","time_in_force"}
        unknown=set(payload)-permitted
        if unknown:raise ValueError(f"Unsupported modification fields: {', '.join(sorted(unknown))}")
        allowed=dict(payload)
        if not allowed: raise ValueError("No modifiable fields supplied")
        if "quantity" in allowed:
            quantity=decimal_field(payload,"quantity",required=True,positive=True,allow_zero=False)
            if quantity<order.filled_quantity:raise ValueError("quantity cannot be less than the already filled quantity")
            allowed["quantity"]=str(quantity)
        for field in ("limit_price","stop_price"):
            if field in allowed:allowed[field]=str(decimal_field(payload,field,required=True,positive=True,allow_zero=False))
        order_type=order.intent.order_type
        if order_type=="MKT" and any(field in allowed for field in ("limit_price","stop_price")):
            raise ValueError("MKT orders cannot be modified with limit_price or stop_price")
        if order_type=="LMT" and "stop_price" in allowed:raise ValueError("LMT orders do not accept stop_price")
        if order_type=="STP" and "limit_price" in allowed:raise ValueError("STP orders do not accept limit_price")
        if "time_in_force" in allowed:
            allowed["time_in_force"]=str(allowed["time_in_force"]).upper()
            if allowed["time_in_force"] not in {"DAY","GTC"}:raise ValueError("time_in_force must be DAY or GTC")
        gateway=GatewayClient.for_order(order,require_commands=True)
        command=gateway.modify_order(order.internal_id,allowed,key); return response({"internal_id":order.internal_id,"status":order.status,"gateway_command":command},status=202)
    except IdempotencyConflict as exc:
        return response(status=409,error={"code":"IDEMPOTENCY_CONFLICT","message":str(exc),"details":{}})
    except (KeyError,ValueError,InvalidOperation,TradingPortfolio.DoesNotExist,Instrument.DoesNotExist,Order.DoesNotExist) as exc:
        return response(status=400,error={"code":"INVALID_ORDER","message":str(exc),"details":{}})
    except GatewayError as exc:
        return response(status=503,error={"code":"GATEWAY_UNAVAILABLE","message":str(exc),"details":{}})

def executions(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
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
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    from apps.reconciliation.models import ReconciliationRun, ReconciliationBreak
    limit,_=_page(request,100)
    runs=ReconciliationRun.objects.select_related("broker_account").order_by("-started_at")
    breaks=ReconciliationBreak.objects.filter(resolved=False).order_by("-created_at")
    if request.GET.get("status"):runs=runs.filter(status=request.GET["status"].upper())
    if request.GET.get("category"):breaks=breaks.filter(category=request.GET["category"])
    if request.GET.get("severity"):breaks=breaks.filter(severity=request.GET["severity"].upper())
    run_rows=[]
    for item in runs[:limit]:
        run_rows.append({"id":item.pk,"broker_account_id":item.broker_account_id,
            "account_id":item.broker_account.account_id if item.broker_account_id else None,
            "trigger":item.trigger,"status":item.status,"started_at":item.started_at,"completed_at":item.completed_at})
    return response({"runs": run_rows,
        "breaks": _serialize(breaks[:limit], ["run_id", "category", "severity", "internal_value", "broker_value", "material", "resolved", "resolution", "created_at"])})

@csrf_exempt
def risk(request):
    from apps.risk.models import KillSwitch, RiskCheckResult
    invalid=method_guard(request,"GET","POST")
    if invalid:return invalid
    if request.method == "POST":
        key=request.headers.get("Idempotency-Key")
        if not key:return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
        try:
            payload = json.loads(request.body or b"{}")
            if not isinstance(payload,dict):raise ValueError("Request body must be a JSON object")
            unknown=set(payload)-{"scope","scope_id","enabled","reason"}
            if unknown:raise ValueError(f"Unsupported risk fields: {', '.join(sorted(unknown))}")
            scope=str(payload.get("scope") or "GLOBAL").upper()
            if scope not in {"GLOBAL","ACCOUNT","PORTFOLIO","STRATEGY_INSTANCE","INSTRUMENT"}:raise ValueError("Unsupported kill-switch scope")
            scope_id=str(payload.get("scope_id") or "")
            if scope=="GLOBAL" and scope_id:raise ValueError("GLOBAL kill switch cannot include scope_id")
            if scope!="GLOBAL" and not scope_id:raise ValueError(f"{scope} kill switch requires scope_id")
            if "enabled" in payload and not isinstance(payload["enabled"],bool):raise ValueError("enabled must be a boolean")
            if scope=="ACCOUNT":
                from apps.accounts.models import BrokerAccount
                from django.db.models import Q
                query=Q(account_id=scope_id)
                if scope_id.isdigit():query|=Q(pk=int(scope_id))
                if not BrokerAccount.objects.filter(query).exists():raise ValueError("Account scope does not exist")
            elif scope=="PORTFOLIO":
                from apps.portfolios.models import TradingPortfolio
                if not TradingPortfolio.objects.filter(pk=scope_id).exists():raise ValueError("Portfolio scope does not exist")
            elif scope=="STRATEGY_INSTANCE":
                from apps.strategies.models import StrategyInstance
                if not StrategyInstance.objects.filter(pk=scope_id).exists():raise ValueError("Strategy instance scope does not exist")
            elif scope=="INSTRUMENT":
                from apps.instruments.models import Instrument
                if not Instrument.objects.filter(pk=scope_id).exists():raise ValueError("Instrument scope does not exist")
            switch, _ = KillSwitch.objects.update_or_create(scope=scope, scope_id=scope_id,
                defaults={"enabled":payload.get("enabled",True),"reason":str(payload.get("reason") or "Operator action")[:255]})
            return response({"id": switch.pk, "enabled": switch.enabled})
        except (json.JSONDecodeError,ValueError,TypeError) as exc:
            return response(status=400,error={"code":"INVALID_RISK_REQUEST","message":str(exc),"details":{}})
    return response({"kill_switches": _serialize(KillSwitch.objects.all(), ["scope", "scope_id", "enabled", "reason", "updated_at"]), "decisions": _serialize(RiskCheckResult.objects.all().order_by("-created_at")[:250], ["order_intent_id", "check_name", "decision", "reason", "requested_quantity", "approved_quantity", "created_at"])})

def audit(request):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    from apps.audit.models import AuditEvent
    limit,offset=_page(request)
    query=AuditEvent.objects.all().order_by("-created_at")
    if request.GET.get("event_type"):query=query.filter(event_type=request.GET["event_type"])
    if request.GET.get("actor"):query=query.filter(actor=request.GET["actor"])
    total=query.count()
    return response(_serialize(query[offset:offset+limit], ["event_type", "actor", "aggregate_type", "aggregate_id", "data", "created_at"]),
        meta={"count":total,"limit":limit,"offset":offset})
