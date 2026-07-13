import json
from django.db import IntegrityError
from django.views.decorators.csrf import csrf_exempt
from apps.core.views import response
from apps.instruments.models import Instrument
from apps.instruments.services import resolve_instrument, search_broker_instruments
from apps.portfolios.models import TradingPortfolio
from .framework import create_instance, enable_instance, evaluate_instance, flatten_instance, pause_instance, update_instance
from .models import OrderPolicy, StrategyDefinition, StrategyInstance, StrategyRiskPolicy
from .plugins import get_plugin


def _definition(item):
    plugin=get_plugin(item)
    return {"id":item.pk,"key":item.key,"name":item.name,"description":item.description,"plugin_path":item.plugin_path,
        "input_requirements":[{"input_type":x.input_type,"name":x.name,"parameters":x.parameters,"warmup_bars":x.warmup_bars}
            for x in plugin.required_stream_inputs(plugin.default_parameters)],
        "parameter_schema":plugin.parameter_schema,"default_parameters":plugin.default_parameters,
        "supported_asset_types":item.supported_asset_types,"supported_directions":item.supported_directions,
        "supported_timeframes":item.supported_timeframes,"version":item.version,"enabled":item.enabled}


def definitions(request, key=None):
    if key:
        try:return response(_definition(StrategyDefinition.objects.get(key=key.upper())))
        except StrategyDefinition.DoesNotExist:return response(status=404,error={"code":"NOT_FOUND","message":"Strategy definition not found","details":{}})
    return response([_definition(x) for x in StrategyDefinition.objects.filter(enabled=True).order_by("name")])


def _instance(item, detail=False):
    from apps.execution.models import Fill
    from apps.market_streams.models import IndicatorValue, MarketBar
    contract=getattr(item.instrument,"broker_contract",None)
    plugin=get_plugin(item.definition)
    latest_bar=MarketBar.objects.filter(instrument=item.instrument,interval=item.timeframe,is_final=True).order_by("-window_end","-version").first()
    latest_signal=item.signals.order_by("-signal_time").first();latest_target=item.targets.order_by("-created_at").first()
    attributed=item.attributed_positions.filter(instrument=item.instrument,portfolio=item.portfolio).first()
    active_attribution=item.legacy_strategy.orderintentattribution_set.filter(order_intent__order__status__in=[
        "CREATED","RISK_APPROVED","QUEUED","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED"]).select_related("order_intent__order").first()
    last_fill=Fill.objects.filter(order__intent__attributions__strategy_instance=item).order_by("-executed_at").first()
    latest_indicators={}
    # Portable across SQLite/PostgreSQL: select the first value for each declared indicator.
    for binding in item.input_bindings.filter(strategy_version__version=item.version,requirement__input_type="INDICATOR").select_related("requirement"):
        requirement=binding.requirement;value=IndicatorValue.objects.filter(instrument=item.instrument,timeframe=item.timeframe,
            parameters_hash=requirement.parameters_hash,is_final=True).order_by("-event_time").first()
        if value:latest_indicators[value.indicator]=value.value
    row={"id":item.pk,"name":item.name,"definition_key":item.definition.key,"definition_name":item.definition.name,
        "portfolio_id":item.portfolio_id,"portfolio":item.portfolio.name,"instrument_id":item.instrument_id,
        "symbol":item.instrument.symbol,"asset_class":item.instrument.asset_class,"exchange":item.instrument.exchange,
        "currency":item.instrument.currency,"conid":contract.conid if contract else None,
        "primary_exchange":contract.primary_exchange if contract else None,"timeframe":item.timeframe,
        "parameters":item.parameters,"target_configuration":item.target_configuration,"risk_policy_id":item.risk_policy_id,
        "order_policy_id":item.order_policy_id,"execution_mode":item.execution_mode,"state":item.state,"enabled":item.enabled,
        "version":item.version,"warmup_progress":item.warmup_progress,"warmup_required":plugin.warmup_bars(item.parameters),
        "block_reason":item.block_reason,"effective_from":item.effective_from,"effective_to":item.effective_to,
        "last_final_bar":latest_bar.window_end if latest_bar else None,"latest_indicators":latest_indicators,
        "latest_signal":latest_signal.signal_type if latest_signal else None,"current_target":latest_target.target_weight if latest_target else None,
        "attributed_quantity":attributed.quantity if attributed else 0,
        "active_order":active_attribution.order_intent.order.internal_id if active_attribution else None,
        "last_fill":last_fill.execution_id if last_fill else None,"cooldown":item.state_data.get("cooldown_until"),
        "created_at":item.created_at,"updated_at":item.updated_at}
    if detail:
        row["versions"]=[{"id":x.pk,"version":x.version,"parameter_hash":x.parameter_hash,"configuration_snapshot":x.configuration_snapshot,
            "created_at":x.created_at,"activated_at":x.activated_at,"retired_at":x.retired_at} for x in item.versions.order_by("-version")]
        row["requirements"]=[{"identity_hash":b.requirement.identity_hash,"input_type":b.requirement.input_type,
            "name":b.requirement.name,"parameters":b.requirement.parameters,"parameters_hash":b.requirement.parameters_hash,
            "warmup_bars":b.requirement.warmup_bars,"shared_by":b.requirement.active_ref_count,"active":b.active}
            for b in item.input_bindings.filter(strategy_version__version=item.version).select_related("requirement")]
    return row


def _get(pk):
    return StrategyInstance.objects.select_related("definition","portfolio","instrument__broker_contract","risk_policy","order_policy","legacy_strategy").get(pk=pk)


@csrf_exempt
def instances(request, instance_id=None):
    try:
        if request.method == "GET":
            if instance_id:return response(_instance(_get(instance_id),True))
            query=StrategyInstance.objects.select_related("definition","portfolio","instrument__broker_contract")
            for field,param in [("portfolio_id","portfolio"),("instrument__symbol","ticker"),("definition__key","strategy_type"),("state","state"),("execution_mode","execution_mode")]:
                if request.GET.get(param):query=query.filter(**{field:request.GET[param]})
            return response([_instance(x) for x in query.order_by("name")])
        payload=json.loads(request.body or b"{}")
        if request.method == "POST":
            portfolio=TradingPortfolio.objects.get(pk=payload["portfolio_id"])
            risk=StrategyRiskPolicy.objects.get(pk=payload["risk_policy_id"]) if payload.get("risk_policy_id") else None
            order=OrderPolicy.objects.get(pk=payload["order_policy_id"]) if payload.get("order_policy_id") else None
            item,qualification=create_instance(name=payload["name"],definition_key=payload["definition_key"],portfolio=portfolio,
                timeframe=payload["timeframe"],parameters=payload.get("parameters",{}),target_configuration=payload.get("target_configuration",{}),
                instrument_id=payload.get("instrument_id"),ticker=payload.get("ticker"),risk_policy=risk,order_policy=order,
                execution_mode=payload.get("execution_mode","SHADOW"),exchange=payload.get("exchange","SMART"),
                currency=payload.get("currency","USD"),primary_exchange=payload.get("primary_exchange"),qualify=payload.get("qualify",True))
            row=_instance(_get(item.pk),True);row["qualification_command"]=qualification
            return response(row,status=201)
        if request.method == "PATCH" and instance_id:
            item=_get(instance_id);changes={}
            for key in ["name","timeframe","parameters","target_configuration","execution_mode"]:
                if key in payload:changes[key]=payload[key]
            if payload.get("definition_key"):changes["definition"]=StrategyDefinition.objects.get(key=payload["definition_key"].upper(),enabled=True)
            if payload.get("risk_policy_id") is not None:changes["risk_policy"]=StrategyRiskPolicy.objects.get(pk=payload["risk_policy_id"])
            if payload.get("order_policy_id") is not None:changes["order_policy"]=OrderPolicy.objects.get(pk=payload["order_policy_id"])
            if payload.get("instrument_id") or payload.get("ticker"):
                changes["instrument"]=resolve_instrument(instrument_id=payload.get("instrument_id"),ticker=payload.get("ticker"),
                    exchange=payload.get("exchange","SMART"),currency=payload.get("currency","USD"),qualify=False)[0]
            return response(_instance(update_instance(item,changes),True))
        return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"Unsupported method","details":{}})
    except (KeyError,ValueError,IntegrityError,StrategyInstance.DoesNotExist,StrategyDefinition.DoesNotExist,
            TradingPortfolio.DoesNotExist,StrategyRiskPolicy.DoesNotExist,OrderPolicy.DoesNotExist,Instrument.DoesNotExist) as exc:
        status=404 if isinstance(exc,StrategyInstance.DoesNotExist) else 400
        return response(status=status,error={"code":"INVALID_STRATEGY_INSTANCE","message":str(exc),"details":{}})


@csrf_exempt
def action(request, instance_id, action_name):
    if request.method!="POST":return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"POST required","details":{}})
    try:
        item=_get(instance_id);payload=json.loads(request.body or b"{}")
        if action_name=="enable":item=enable_instance(item);return response(_instance(item,True))
        if action_name=="pause":item=pause_instance(item);return response(_instance(item,True))
        if action_name in {"evaluate","flatten"}:
            if action_name=="flatten":
                run=flatten_instance(item,event_id=payload.get("event_id"))
            else:
                run=evaluate_instance(item,bar=payload.get("bar",{"is_final":True}),indicators=payload.get("indicators",{}),
                    previous_indicators=payload.get("previous_indicators",{}),event_id=payload.get("event_id"),
                    source_data_version=int(payload.get("source_data_version",1)),force=bool(payload.get("force",False)))
            if action_name=="flatten" and payload.get("reason"):
                from apps.audit.models import AuditEvent
                AuditEvent.objects.get_or_create(idempotency_key=f"audit:strategy:{item.pk}:flatten:{run.pk}",defaults={
                    "event_type":"strategy.flatten.requested","actor":"frontend_operator","aggregate_type":"strategy_instance",
                    "aggregate_id":str(item.pk),"data":{"reason":payload["reason"],"strategy_run_id":run.pk}})
            return response({"id":run.pk,"status":run.status,"error":run.error,"target_ids":list(run.targets.values_list("pk",flat=True))},status=201)
        return response(status=404,error={"code":"NOT_FOUND","message":"Unknown action","details":{}})
    except (ValueError,StrategyInstance.DoesNotExist) as exc:
        return response(status=400,error={"code":"STRATEGY_ACTION_FAILED","message":str(exc),"details":{}})


def related(request, instance_id, resource):
    try:item=_get(instance_id)
    except StrategyInstance.DoesNotExist:return response(status=404,error={"code":"NOT_FOUND","message":"Strategy instance not found","details":{}})
    if resource=="state":return response(_instance(item,True))
    if resource=="runs":return response([{"id":x.pk,"version":x.strategy_version.version if x.strategy_version else None,
        "status":x.status,"triggering_event_id":x.triggering_event_id,"source_data_version":x.source_data_version,
        "started_at":x.started_at,"completed_at":x.completed_at,"error":x.error} for x in item.runs.order_by("-started_at")[:100]])
    if resource=="signals":return response([{"id":x.pk,"run_id":x.run_id,"version":x.strategy_version.version,
        "signal_type":x.signal_type,"signal_time":x.signal_time,"reason":x.reason,"details":x.details} for x in item.signals.order_by("-signal_time")[:100]])
    if resource=="targets":return response([{"id":x.pk,"run_id":x.run_id,"version":x.strategy_version.version if x.strategy_version else None,
        "target_type":x.target_type,"target_weight":x.target_weight,"target_value":x.target_value,"target_quantity":x.target_quantity,
        "direction":x.direction,"signal_type":x.signal_type,"signal_time":x.signal_time,"source_event_id":x.source_event_id,
        "reason":x.reason,"status":x.status} for x in item.targets.order_by("-created_at")[:100]])
    if resource=="execution-timeline":
        rows=[]
        for run in item.runs.order_by("-started_at")[:100]:rows.append({"time":run.started_at,"type":"RUN","id":run.pk,"status":run.status,"version":run.strategy_version.version if run.strategy_version else None})
        for signal in item.signals.order_by("-signal_time")[:100]:rows.append({"time":signal.signal_time,"type":"SIGNAL","id":signal.pk,"status":signal.signal_type,"version":signal.strategy_version.version})
        for target in item.targets.order_by("-created_at")[:100]:rows.append({"time":target.created_at,"type":"TARGET","id":target.pk,"status":target.status,"version":target.strategy_version.version if target.strategy_version else None})
        for attribution in item.legacy_strategy.orderintentattribution_set.select_related("order_intent__order").all():
            intent=attribution.order_intent
            rows.append({"time":intent.created_at,"type":"ORDER_INTENT","id":intent.pk,
                "status":"ELIGIBLE" if intent.eligible else "HELD","version":attribution.strategy_version.version if attribution.strategy_version else None,
                "detail":f"{intent.side} {intent.quantity} {item.instrument.symbol}"})
            order=getattr(intent,"order",None)
            if order:
                rows.append({"time":order.created_at,"type":"ORDER","id":order.pk,"status":order.status,
                    "version":attribution.strategy_version.version if attribution.strategy_version else None,"detail":order.internal_id})
                for fill in order.fills.all():
                    rows.append({"time":fill.executed_at,"type":"FILL","id":fill.pk,"status":"FILLED",
                        "version":attribution.strategy_version.version if attribution.strategy_version else None,
                        "detail":f"{fill.quantity} @ {fill.price}"})
        return response(sorted(rows,key=lambda x:x["time"],reverse=True))
    return response(status=404,error={"code":"NOT_FOUND","message":"Unknown resource","details":{}})


def chart(request, instance_id):
    from apps.market_streams.models import IndicatorValue, MarketBar
    try:
        item=_get(instance_id)
    except StrategyInstance.DoesNotExist:
        return response(status=404,error={"code":"NOT_FOUND","message":"Strategy instance not found","details":{}})
    raw_bars=list(MarketBar.objects.filter(instrument=item.instrument,interval=item.timeframe,is_final=True)
        .order_by("-window_end","-version")[:500])
    latest={}
    for bar in raw_bars:
        if bar.bar_id not in latest:latest[bar.bar_id]=bar
    bars=sorted(latest.values(),key=lambda x:x.window_end)
    start=bars[0].window_start if bars else None
    indicators=IndicatorValue.objects.filter(instrument=item.instrument,timeframe=item.timeframe,is_final=True)
    if start:indicators=indicators.filter(event_time__gte=start)
    indicators=indicators.order_by("event_time")[:2000]
    markers=[]
    for signal in item.signals.order_by("signal_time"):
        markers.append({"time":signal.signal_time,"type":"SIGNAL","label":f"Signal {signal.signal_type}"})
    for target in item.targets.order_by("created_at"):
        markers.append({"time":target.created_at,"type":"TARGET","label":f"Target {target.target_weight}","value":target.target_weight})
    for attribution in item.legacy_strategy.orderintentattribution_set.select_related("order_intent__order").all():
        order=getattr(attribution.order_intent,"order",None)
        if not order:continue
        markers.append({"time":order.created_at,"type":"ORDER","label":f"Order {attribution.order_intent.side} {order.status}","value":order.quantity})
        for fill in order.fills.all():
            markers.append({"time":fill.executed_at,"type":"FILL","label":f"Fill {fill.quantity} @ {fill.price}","value":fill.price})
    return response({
        "bars":[{"time":bar.window_end,"open":bar.open,"high":bar.high,"low":bar.low,"close":bar.close,
            "volume":bar.volume,"version":bar.version} for bar in bars],
        "indicators":[{"time":value.event_time,"name":value.indicator,"value":value.value} for value in indicators if value.value is not None],
        "markers":sorted(markers,key=lambda x:x["time"]),
        "source":"POSTGRES_MARKET_AND_EXECUTION_FACTS",
    })


def policies(request):
    return response({"risk_policies":[{"id":x.pk,"name":x.name,"maximum_weight":x.maximum_weight,"maximum_notional":x.maximum_notional,
        "maximum_quantity":x.maximum_quantity,"allow_short":x.allow_short} for x in StrategyRiskPolicy.objects.filter(enabled=True)],
        "order_policies":[{"id":x.pk,"name":x.name,"order_type":x.order_type,"time_in_force":x.time_in_force,
        "limit_offset_bps":x.limit_offset_bps,"price_collar_bps":x.price_collar_bps,"allow_market_order":x.allow_market_order,
        "replace_after_seconds":x.replace_after_seconds,"maximum_replacements":x.maximum_replacements,
        "cancel_at_session_end":x.cancel_at_session_end,"outside_regular_hours":x.outside_regular_hours} for x in OrderPolicy.objects.filter(enabled=True)]})


@csrf_exempt
def resolve(request):
    try:
        payload=json.loads(request.body or b"{}") if request.method=="POST" else request.GET
        instrument,contract,command=resolve_instrument(instrument_id=payload.get("instrument_id"),ticker=payload.get("ticker"),
            asset_class=payload.get("asset_class","STK"),exchange=payload.get("exchange","SMART"),currency=payload.get("currency","USD"),
            primary_exchange=payload.get("primary_exchange"),conid=payload.get("conid"),local_symbol=payload.get("local_symbol"),
            description=payload.get("description"),qualify=bool(payload.get("qualify",request.method=="POST")))
        return response({"instrument_id":instrument.pk,"symbol":instrument.symbol,"asset_class":instrument.asset_class,
            "exchange":instrument.exchange,"currency":instrument.currency,"conid":contract.conid if contract else None,
            "primary_exchange":contract.primary_exchange if contract else None,"qualification_command":command})
    except Exception as exc:return response(status=400,error={"code":"INSTRUMENT_RESOLUTION_FAILED","message":str(exc),"details":{}})


def search_instruments(request):
    try:return response(search_broker_instruments(request.GET.get("query")))
    except Exception as exc:return response(status=502,error={"code":"INSTRUMENT_SEARCH_FAILED","message":str(exc),"details":{}})
