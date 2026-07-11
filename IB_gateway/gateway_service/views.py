import json, secrets, uuid
from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import GatewayCommand, GatewayEvent, GatewayOrderReference, GatewaySession
from .services import enqueue

def response(data=None, status=200, error=None, meta=None): return JsonResponse({"ok":error is None,"data":data if error is None else None,"error":error,"meta":meta or {}},status=status,safe=False)
def _auth(request):
    supplied=request.headers.get("Authorization","")
    return secrets.compare_digest(supplied, f"Bearer {settings.GATEWAY_SERVICE_TOKEN}")
def protected(fn):
    def wrapped(request,*args,**kwargs):
        if not _auth(request): return response(status=401,error={"code":"UNAUTHORIZED","message":"Valid service token required","details":{}})
        return fn(request,*args,**kwargs)
    return wrapped
def healthz(request):
    with connection.cursor() as cursor: cursor.execute("SELECT 1")
    return response({"status":"healthy"})
def _payload(request): return json.loads(request.body or b"{}")
def _key(request): return request.headers.get("Idempotency-Key") or str(uuid.uuid4())

@protected
def health(request):
    session=GatewaySession.objects.filter(pk=1).first()
    return response({"connected":bool(session and session.state=="CONNECTED"),"reconciled":bool(session and session.reconciled),"mode":settings.IBC_TRADING_MODE,"last_callback":session.last_callback_at if session else None,"worker":session.connection_owner if session else ""})
@protected
def session(request):
    value=GatewaySession.objects.filter(pk=1).values().first() or {"state":"DISCONNECTED","mode":settings.IBC_TRADING_MODE,"reconciled":False}
    return response(value)
@csrf_exempt
@protected
def reconnect(request):
    command=enqueue("RECONNECT",{},_key(request)); return response({"command_id":command.pk,"status":command.status},202)
def _latest(event_type, default):
    event=GatewayEvent.objects.filter(event_type=event_type).order_by("-id").first(); return event.payload.get("value",default) if event else default
@protected
def accounts(request): return response(_latest("snapshot.accounts",[]))
@protected
def account_summary(request): return response(_latest("snapshot.account_summary",[]))
@protected
def positions(request): return response(_latest("snapshot.positions",[]))
@protected
def open_orders(request): return response(_latest("snapshot.open_orders",[]))
@protected
def executions(request): return response(_latest("snapshot.executions",[]))
@csrf_exempt
@protected
def qualify(request):
    command=enqueue("QUALIFY",_payload(request),_key(request)); return response({"command_id":command.pk,"status":command.status},202)
@csrf_exempt
@protected
def orders(request, internal_id=None):
    payload=_payload(request)
    if internal_id: payload["internal_id"]=internal_id
    command=enqueue("MODIFY_ORDER" if internal_id else "PLACE_ORDER",payload,_key(request)); return response({"command_id":command.pk,"status":command.status},202)
@csrf_exempt
@protected
def cancel(request,internal_id):
    command=enqueue("CANCEL_ORDER",{"internal_id":internal_id},_key(request)); return response({"command_id":command.pk,"status":command.status},202)
@protected
def events(request):
    after=int(request.GET.get("after",0)); rows=list(GatewayEvent.objects.filter(id__gt=after).order_by("id")[:500].values("id","event_type","payload","created_at"))
    return response(rows,meta={"next_sequence":rows[-1]["id"] if rows else after})
@csrf_exempt
@protected
def ack(request):
    sequence=int(_payload(request).get("sequence",0)); count=GatewayEvent.objects.filter(id__lte=sequence,acknowledged=False).update(acknowledged=True); return response({"acknowledged":count,"sequence":sequence})
@csrf_exempt
@protected
def kill_switch(request):
    command=enqueue("KILL_SWITCH",_payload(request),_key(request)); return response({"command_id":command.pk,"status":command.status},202)

