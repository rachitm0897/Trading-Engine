import json, secrets
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .diagnostics import collect_gateway_diagnostics, readiness_state
from .models import GatewayCommand, GatewayEvent, GatewayOrderReference, GatewaySession
from .services import CommandRetryNotAllowed, IdempotencyConflict, enqueue

def response(data=None, status=200, error=None, meta=None): return JsonResponse({"ok":error is None,"data":data if error is None else None,"error":error,"meta":meta or {}},status=status,safe=False)
def _auth(request):
    supplied=request.headers.get("Authorization","")
    return secrets.compare_digest(supplied, f"Bearer {settings.GATEWAY_SERVICE_TOKEN}")
def protected(fn):
    def wrapped(request,*args,**kwargs):
        if not _auth(request): return response(status=401,error={"code":"UNAUTHORIZED","message":"Valid service token required","details":{}})
        try:return fn(request,*args,**kwargs)
        except (json.JSONDecodeError,ValueError,TypeError,InvalidOperation) as exc:
            return response(status=400,error={"code":"INVALID_REQUEST","message":str(exc),"details":{}})
    return wrapped
def healthz(request):
    invalid=_method(request,"GET")
    if invalid:return invalid
    return response({"status":"alive"})
def readyz(request):
    invalid=_method(request,"GET")
    if invalid:return invalid
    diagnostics=collect_gateway_diagnostics()
    ready,state,details=readiness_state(
        diagnostics,settings.BROKER_ADAPTER,settings.IBC_TRADING_MODE
    )
    if ready:return response({"status":"ready"})
    return response(status=503,error={
        "code":"GATEWAY_NOT_READY",
        "message":"Gateway internal services are not ready",
        "details":{"status":state,"fatal":False,**details},
    })
def _payload(request):
    value=json.loads(request.body or b"{}")
    if not isinstance(value,dict):raise ValueError("Request body must be a JSON object")
    return value
def _method(request,*allowed):
    if request.method not in allowed:return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":f"{' or '.join(allowed)} required","details":{}})
    return None
def _key(request): return request.headers.get("Idempotency-Key")
def _retry(request): return request.headers.get("Idempotency-Retry", "").strip().lower() in {"1", "true", "yes"}
def _queued(request, command_type, payload):
    key=_key(request)
    if not key:return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    try:
        command=enqueue(command_type,payload,key,retry_failed=_retry(request))
    except IdempotencyConflict as exc:
        return response(status=409,error={"code":"IDEMPOTENCY_CONFLICT","message":str(exc),"details":{}})
    except CommandRetryNotAllowed as exc:
        return response(status=409,error={"code":"RETRY_NOT_ALLOWED","message":str(exc),"details":{}})
    return response({"command_id":command.pk,"status":command.status},202)

@protected
def health(request):
    invalid=_method(request,"GET")
    if invalid:return invalid
    session=GatewaySession.objects.filter(pk=1).first()
    return response({"connected":bool(session and session.state=="CONNECTED"),"reconciled":bool(session and session.reconciled),"mode":settings.IBC_TRADING_MODE,"last_callback":session.last_callback_at if session else None,"worker":session.connection_owner if session else "","connection_generation":str(session.connection_generation) if session else ""})
@protected
def diagnostics(request):
    invalid=_method(request,"GET")
    if invalid:return invalid
    return response(collect_gateway_diagnostics())
@protected
def session(request):
    invalid=_method(request,"GET")
    if invalid:return invalid
    value=GatewaySession.objects.filter(pk=1).values().first() or {"state":"DISCONNECTED","mode":settings.IBC_TRADING_MODE,"reconciled":False}
    return response(value)
@csrf_exempt
@protected
def reconnect(request):
    invalid=_method(request,"POST")
    if invalid:return invalid
    return _queued(request,"RECONNECT",{})
def _latest(event_type, default):
    event=GatewayEvent.objects.filter(event_type=event_type).order_by("-id").first(); return event.payload.get("value",default) if event else default
@protected
def accounts(request):
    invalid=_method(request,"GET")
    return invalid or response(_latest("snapshot.accounts",[]))
@protected
def account_summary(request):
    invalid=_method(request,"GET")
    return invalid or response(_latest("snapshot.account_summary",[]))
@protected
def positions(request):
    invalid=_method(request,"GET")
    return invalid or response(_latest("snapshot.positions_all",[]))
@protected
def open_orders(request):
    invalid=_method(request,"GET")
    return invalid or response(_latest("snapshot.open_orders",[]))
@protected
def completed_orders(request):
    invalid=_method(request,"GET")
    return invalid or response(_latest("snapshot.completed_orders",[]))
@protected
def order_state(request, internal_id):
    invalid=_method(request,"GET")
    if invalid:return invalid
    commands=[]
    for command in GatewayCommand.objects.filter(
            command_type__in=["PLACE_ORDER","MODIFY_ORDER","CANCEL_ORDER"]).order_by("id"):
        if str((command.payload or {}).get("internal_id") or "") != str(internal_id):
            continue
        commands.append({"command_id":command.pk,"command_type":command.command_type,
            "status":command.status,"result":command.result,"last_error":command.last_error,
            "retryable":command.retryable,"attempt_count":command.attempt_count,
            "completed_at":command.completed_at})
    reference=GatewayOrderReference.objects.filter(internal_id=internal_id).values(
        "internal_id","broker_order_id","permanent_id","last_status","updated_at").first()
    broker_order=None
    for row in [*_latest("snapshot.open_orders",[]),*_latest("snapshot.completed_orders",[])]:
        if str(row.get("internal_id") or "") == str(internal_id):
            broker_order=row
            break
    return response({"internal_id":internal_id,"commands":commands,"reference":reference or {},
        "broker_order":broker_order or {},
        "non_submission_established":not commands and reference is None and broker_order is None})
@protected
def executions(request):
    invalid=_method(request,"GET")
    return invalid or response(_latest("snapshot.executions",[]))
@csrf_exempt
@protected
def contract_search(request):
    invalid=_method(request,"POST")
    if invalid:return invalid
    payload=_payload(request)
    query=str(payload.get("query","")).strip()
    if not query: return response(status=400,error={"code":"QUERY_REQUIRED","message":"Instrument search query is required","details":{}})
    return _queued(request,"SEARCH_CONTRACTS",{"query":query})
@csrf_exempt
@protected
def qualify(request):
    invalid=_method(request,"POST")
    if invalid:return invalid
    payload=_payload(request)
    if not payload.get("conid") and not str(payload.get("symbol") or "").strip():raise ValueError("conid or symbol is required")
    return _queued(request,"QUALIFY",payload)
@csrf_exempt
@protected
def historical_data(request):
    invalid=_method(request,"POST")
    if invalid:return invalid
    payload=_payload(request)
    allowed={"conid","symbol","exchange","currency","bar_size","duration","what_to_show","use_rth","end_time"}
    unknown=set(payload)-allowed
    if unknown:raise ValueError(f"Unsupported historical-data fields: {', '.join(sorted(unknown))}")
    required=("conid","symbol","exchange","currency","bar_size","duration","what_to_show","use_rth")
    missing=[key for key in required if payload.get(key) in (None,"")]
    if missing:raise ValueError(f"Missing fields: {', '.join(missing)}")
    if int(payload["conid"]) <= 0:raise ValueError("conid must be positive")
    bar_sizes={"1 min":"1 min","1m":"1 min","5 mins":"5 mins","5m":"5 mins","15 mins":"15 mins","15m":"15 mins","1 hour":"1 hour","1h":"1 hour","1 day":"1 day","1d":"1 day"}
    bar_size=bar_sizes.get(str(payload["bar_size"]).lower())
    if not bar_size:raise ValueError("bar_size must be 1 min, 5 mins, 15 mins, 1 hour, or 1 day")
    match=re.fullmatch(r"([1-9][0-9]*)\s+([DWMY])",str(payload["duration"]).strip().upper())
    if not match:raise ValueError("duration must use bounded D, W, M, or Y units")
    amount,unit=int(match.group(1)),match.group(2)
    approximate_days=amount*({"D":1,"W":7,"M":31,"Y":366}[unit])
    if bar_size=="1 day" and approximate_days>3660:raise ValueError("daily duration cannot exceed ten years")
    if bar_size!="1 day" and approximate_days>90:raise ValueError("intraday duration cannot exceed ninety days")
    what=str(payload["what_to_show"]).upper()
    if what not in {"TRADES","ADJUSTED_LAST"}:raise ValueError("what_to_show must be TRADES or ADJUSTED_LAST")
    if not isinstance(payload["use_rth"],bool):raise ValueError("use_rth must be a boolean")
    if payload.get("end_time"):
        datetime.fromisoformat(str(payload["end_time"]).replace("Z","+00:00"))
    normalized={**payload,"conid":int(payload["conid"]),"bar_size":bar_size,"duration":f"{amount} {unit}",
                "what_to_show":what}
    return _queued(request,"REQUEST_HISTORICAL_DATA",normalized)

@csrf_exempt
@protected
def historical_schedule(request):
    invalid=_method(request,"POST")
    if invalid:return invalid
    payload=_payload(request)
    allowed={"conid","symbol","exchange","currency","days","use_rth","end_time"}
    unknown=set(payload)-allowed
    if unknown:raise ValueError(f"Unsupported historical-schedule fields: {', '.join(sorted(unknown))}")
    required=("conid","symbol","exchange","currency","days","use_rth")
    missing=[key for key in required if payload.get(key) in (None,"")]
    if missing:raise ValueError(f"Missing fields: {', '.join(missing)}")
    days=int(payload["days"])
    if int(payload["conid"])<=0 or not 1<=days<=365:raise ValueError("conid and days are out of range")
    if not isinstance(payload["use_rth"],bool):raise ValueError("use_rth must be a boolean")
    normalized={**payload,"conid":int(payload["conid"]),"days":days}
    return _queued(request,"REQUEST_HISTORICAL_SCHEDULE",normalized)
@csrf_exempt
@protected
def market_subscription(request, action=None):
    invalid=_method(request,"POST")
    if invalid:return invalid
    payload=_payload(request)
    required=("subscription_key",) if action=="cancel" else ("subscription_key","instrument_id","conid","symbol","timeframe")
    missing=[key for key in required if payload.get(key) in (None,"")]
    if missing:return response(status=400,error={"code":"INVALID_SUBSCRIPTION","message":f"Missing fields: {','.join(missing)}","details":{}})
    return _queued(request,"CANCEL_MARKET_DATA" if action=="cancel" else "SUBSCRIBE_MARKET_DATA",payload)
@csrf_exempt
@protected
def orders(request, internal_id=None):
    invalid=_method(request,"PATCH" if internal_id else "POST")
    if invalid:return invalid
    payload=_payload(request)
    if internal_id: payload["internal_id"]=internal_id
    allowed={"internal_id","account","symbol","conid","asset_class","exchange","currency","side","quantity",
        "order_type","limit_price","stop_price","time_in_force"} if not internal_id else {
            "internal_id","quantity","limit_price","stop_price","time_in_force"
        }
    unknown=set(payload)-allowed
    if unknown:raise ValueError(f"Unsupported order fields: {', '.join(sorted(unknown))}")
    if not internal_id:
        missing=[field for field in ("internal_id","account","side","quantity") if payload.get(field) in (None,"")]
        if missing:raise ValueError(f"Missing fields: {', '.join(missing)}")
        if not payload.get("symbol") and not payload.get("conid"):raise ValueError("symbol or conid is required")
        if str(payload["side"]).upper() not in {"BUY","SELL"}:raise ValueError("side must be BUY or SELL")
        order_type=str(payload.get("order_type") or "MKT").upper()
        if order_type not in {"MKT","LMT","STP","STP_LMT"}:raise ValueError("order_type must be MKT, LMT, STP, or STP_LMT")
    if "time_in_force" in payload and str(payload["time_in_force"]).upper() not in {"DAY","GTC"}:
        raise ValueError("time_in_force must be DAY or GTC")
    if "quantity" in payload:
        quantity=Decimal(str(payload["quantity"]))
        if not quantity.is_finite() or quantity<=0 or max(-quantity.as_tuple().exponent,0)>8:raise ValueError("quantity must be positive with at most 8 decimal places")
    order_type=str(payload.get("order_type") or "MKT").upper()
    for field in ("limit_price","stop_price"):
        if payload.get(field) not in (None,""):
            value=Decimal(str(payload[field]))
            if not value.is_finite() or value<=0 or max(-value.as_tuple().exponent,0)>8:raise ValueError(f"{field} must be positive with at most 8 decimal places")
    if not internal_id and order_type in {"LMT","STP_LMT"} and payload.get("limit_price") in (None,""):raise ValueError(f"{order_type} requires limit_price")
    if not internal_id and order_type in {"STP","STP_LMT"} and payload.get("stop_price") in (None,""):raise ValueError(f"{order_type} requires stop_price")
    if not internal_id and order_type=="MKT" and any(payload.get(field) not in (None,"") for field in ("limit_price","stop_price")):
        raise ValueError("MKT does not accept limit_price or stop_price")
    if internal_id and not (set(payload)-{"internal_id"}):raise ValueError("At least one modification field is required")
    return _queued(request,"MODIFY_ORDER" if internal_id else "PLACE_ORDER",payload)
@csrf_exempt
@protected
def cancel(request,internal_id):
    invalid=_method(request,"POST")
    if invalid:return invalid
    return _queued(request,"CANCEL_ORDER",{"internal_id":internal_id})
@protected
def events(request):
    invalid=_method(request,"GET")
    if invalid:return invalid
    requested_after=int(request.GET.get("after",0))
    latest=GatewayEvent.objects.order_by("-id").values_list("id",flat=True).first() or 0
    reset=requested_after>latest and latest>0
    after=0 if reset else requested_after
    rows=list(GatewayEvent.objects.filter(id__gt=after).order_by("id")[:500].values("id","event_type","payload","created_at"))
    return response(rows,meta={"next_sequence":rows[-1]["id"] if rows else after,"latest_sequence":latest,"sequence_reset":reset})
@csrf_exempt
@protected
def ack(request):
    invalid=_method(request,"POST")
    if invalid:return invalid
    if not _key(request):return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    sequence=int(_payload(request).get("sequence",0))
    if sequence<=0:raise ValueError("sequence must be positive")
    count=GatewayEvent.objects.filter(id__lte=sequence,acknowledged=False).update(acknowledged=True); return response({"acknowledged":count,"sequence":sequence})
@csrf_exempt
@protected
def kill_switch(request):
    invalid=_method(request,"POST")
    if invalid:return invalid
    payload=_payload(request)
    if not isinstance(payload.get("enabled"),bool):raise ValueError("enabled must be a boolean")
    return _queued(request,"KILL_SWITCH",payload)
@protected
def command_detail(request, command_id):
    invalid=_method(request,"GET")
    if invalid:return invalid
    try: command=GatewayCommand.objects.get(pk=command_id)
    except GatewayCommand.DoesNotExist:return response(status=404,error={"code":"NOT_FOUND","message":"Gateway command not found","details":{}})
    return response({"command_id":command.pk,"command_type":command.command_type,"status":command.status,
        "request_hash":command.request_hash,"result":command.result,"last_error":command.last_error,
        "retryable":command.retryable,"claimed_by":command.claimed_by,"claimed_at":command.claimed_at,
        "lease_expires_at":command.lease_expires_at,"attempt_count":command.attempt_count,
        "completed_at":command.completed_at,"updated_at":command.updated_at})
