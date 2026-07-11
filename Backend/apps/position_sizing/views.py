import json
from decimal import Decimal, InvalidOperation
from django.views.decorators.csrf import csrf_exempt
from apps.core.views import response
from apps.instruments.models import Instrument
from apps.portfolios.models import TradingPortfolio
from .models import PositionSizingDecision, PositionSizingPolicy
from .services import size_and_record


def _row(item):
    return {key:getattr(item,key) for key in ["id","policy_id","instrument_id","side","target_quantity","risk_quantity",
        "weight_quantity","liquidity_quantity","cash_quantity","broker_quantity","approved_quantity","entry_price",
        "stop_price","risk_budget","binding_constraint","limits","calculation_version","rejected_reason","created_at"]}


@csrf_exempt
def preview(request):
    if request.method != "POST":return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"POST required","details":{}})
    key=request.headers.get("Idempotency-Key")
    if not key:return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    try:
        p=json.loads(request.body or b"{}"); portfolio=TradingPortfolio.objects.select_related("account").get(pk=p["portfolio_id"])
        instrument=Instrument.objects.get(pk=p["instrument_id"])
        policy=PositionSizingPolicy.objects.filter(portfolio=portfolio,enabled=True).first() or PositionSizingPolicy.objects.create(portfolio=portfolio)
        item=size_and_record(policy,instrument,p.get("side","BUY"),Decimal(str(p["target_quantity"])),Decimal(str(p["entry_price"])),
            Decimal(str(p["stop_price"])) if p.get("stop_price") is not None else None,
            Decimal(str(p.get("nav",portfolio.account.net_liquidation))),Decimal(str(p.get("available_cash",portfolio.account.available_cash))),
            Decimal(str(p.get("adv",0))),broker_limits=p.get("broker_limits",{}),idempotency_key=key)
        return response(_row(item),status=201)
    except (KeyError,ValueError,InvalidOperation,TradingPortfolio.DoesNotExist,Instrument.DoesNotExist) as exc:
        return response(status=400,error={"code":"INVALID_SIZING","message":str(exc),"details":{}})


def decision(request, decision_id):
    try:return response(_row(PositionSizingDecision.objects.get(pk=decision_id)))
    except PositionSizingDecision.DoesNotExist:return response(status=404,error={"code":"NOT_FOUND","message":"Sizing decision not found","details":{}})
