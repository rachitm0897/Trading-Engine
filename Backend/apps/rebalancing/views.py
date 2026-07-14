import json, uuid
from decimal import Decimal, InvalidOperation
from django.conf import settings
from apps.core.views import response, _serialize
from apps.portfolios.models import TradingPortfolio
from apps.allocation.models import RebalancePolicy, RebalanceRun
from .services import plan_rebalance


def policies(request):
    return response(_serialize(RebalancePolicy.objects.all(),["portfolio_id","instrument_drift_threshold","portfolio_drift_threshold",
        "minimum_trade_notional","minimum_trade_quantity","cash_buffer_percent","fee_buffer","maximum_turnover",
        "sell_before_buy","price_staleness_limit","partial_fill_threshold","mode","enabled","updated_at"]))


def _row(run, detail=False):
    row={"id":run.pk,"portfolio_id":run.portfolio_id,"trigger":run.trigger,"mode":run.mode,"status":run.status,
        "phase":run.phase,"nav":run.nav,"total_drift":run.total_drift,"planned_turnover":run.planned_turnover,
        "target_source":run.target_source,"optimization_run_id":run.optimization_run_id,
        "created_at":run.created_at,"last_recalculated_at":run.last_recalculated_at}
    if detail:
        row["targets"]=_serialize(run.targets.select_related("instrument"),["instrument_id","target_weight","current_weight","drift",
            "current_quantity","target_quantity","trade_quantity","reference_price","estimated_cost","suppressed","suppression_reason","rank"])
        row["intents"]=_serialize(run.orderintent_set.all(),["instrument_id","side","quantity","eligible","execution_priority","idempotency_key"])
    return row


def execute(request, preview=False):
    if request.method != "POST":return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"POST required","details":{}})
    key=request.headers.get("Idempotency-Key")
    if not key:return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    try:
        payload=json.loads(request.body or b"{}")
        portfolio=TradingPortfolio.objects.select_related("account").get(pk=payload["portfolio_id"])
        mode="SHADOW" if preview or settings.NEW_EXECUTION_MODE=="SHADOW" else "PAPER"
        prices={int(k) if str(k).isdigit() else k:v for k,v in payload.get("prices",{}).items()}
        run=plan_rebalance(portfolio,payload.get("trigger","MANUAL"),key,prices=prices or None,
            nav=payload.get("nav"),mode=mode,strict_market_state=not bool(prices))
        return response(_row(run,True),status=201)
    except (KeyError,ValueError,InvalidOperation,TradingPortfolio.DoesNotExist) as exc:
        return response(status=400,error={"code":"INVALID_REBALANCE","message":str(exc),"details":{}})


def runs(request, run_id=None):
    if run_id:
        try:return response(_row(RebalanceRun.objects.get(pk=run_id),True))
        except RebalanceRun.DoesNotExist:return response(status=404,error={"code":"NOT_FOUND","message":"Rebalance run not found","details":{}})
    return response([_row(x) for x in RebalanceRun.objects.order_by("-created_at")[:100]])
