import json
from decimal import Decimal, InvalidOperation
from django.views.decorators.csrf import csrf_exempt
from apps.core.views import response, _serialize
from apps.portfolios.models import TradingPortfolio
from apps.strategies.models import StrategyAllocation
from .models import AllocationRun
from .services import create_flow


def policies(request):
    rows=[]
    for item in StrategyAllocation.objects.select_related("strategy","portfolio"):
        rows.append({"id":item.pk,"portfolio_id":item.portfolio_id,"portfolio":item.portfolio.name,
            "strategy_id":item.strategy_id,"strategy":item.strategy.name,"target_share":item.weight,
            "minimum_share":item.minimum_share,"maximum_share":item.maximum_share,"capacity":item.capacity,
            "minimum_allocation":item.minimum_allocation,"priority":item.priority,"enabled":item.strategy.enabled})
    return response(rows)


@csrf_exempt
def flows(request):
    if request.method != "POST": return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"POST required","details":{}})
    key=request.headers.get("Idempotency-Key")
    if not key:return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    try:
        payload=json.loads(request.body or b"{}")
        run=create_flow(TradingPortfolio.objects.select_related("account").get(pk=payload["portfolio_id"]),
            payload["flow_type"].upper(),Decimal(str(payload["amount"])),key,nav=payload.get("nav"),
            liquidation_policy=payload.get("liquidation_policy","PROPORTIONAL"))
        return response({"id":run.pk,"flow_id":run.flow_id,"status":run.status,"unallocated_amount":run.unallocated_amount},status=201)
    except (KeyError,ValueError,InvalidOperation,TradingPortfolio.DoesNotExist) as exc:
        return response(status=400,error={"code":"INVALID_FLOW","message":str(exc),"details":{}})


def _run(item, detail=False):
    row={"id":item.pk,"flow_id":item.flow_id,"portfolio_id":item.flow.portfolio_id,"flow_type":item.flow.flow_type,
        "amount":item.flow.amount,"approved_amount":item.approved_amount,"unallocated_amount":item.unallocated_amount,
        "liquidation_policy":item.liquidation_policy,"status":item.status,"created_at":item.created_at}
    if detail:
        row["snapshots"]=_serialize(item.capital_snapshots.all(),["strategy_id","capital_before","target_capital","deficit","surplus","idle_cash"])
        row["decisions"]=_serialize(item.decisions.all(),["strategy_id","source","requested_amount","approved_amount","binding_constraint","liquidation_required","rank","details"])
    return row


def runs(request, run_id=None):
    if run_id:
        try:return response(_run(AllocationRun.objects.select_related("flow").get(pk=run_id),True))
        except AllocationRun.DoesNotExist:return response(status=404,error={"code":"NOT_FOUND","message":"Allocation run not found","details":{}})
    return response([_run(x) for x in AllocationRun.objects.select_related("flow").order_by("-created_at")[:100]])
