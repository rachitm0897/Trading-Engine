import json
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Prefetch, Subquery
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from apps.core.views import method_guard, response
from apps.core.idempotency import IdempotencyConflict, canonical_request_hash, require_matching_request
from apps.instruments.models import Instrument
from apps.instruments.services import resolve_instrument, search_broker_instruments
from apps.portfolios.models import TradingPortfolio
from .deletion import (
    StrategyDeletionError,
    audit_strategy_deletion_rejection,
    delete_strategy_instance,
)
from .framework import create_instance, enable_instance, evaluate_instance, flatten_instance, pause_instance, update_instance
from .models import (OrderPolicy, StrategyAction, StrategyAttributedPosition, StrategyDefinition,
    StrategyInputBinding, StrategyInstance, StrategyRiskPolicy, StrategyRun)
from .models import StrategyVersion
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
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    if key:
        try:return response(_definition(StrategyDefinition.objects.get(key=key.upper())))
        except StrategyDefinition.DoesNotExist:return response(status=404,error={"code":"NOT_FOUND","message":"Strategy definition not found","details":{}})
    return response([_definition(x) for x in StrategyDefinition.objects.filter(enabled=True).order_by("name")])


def _strategy_queryset(detail=False):
    from apps.allocation.models import OrderIntentAttribution
    from apps.execution.models import Fill
    from apps.market_streams.health import annotate_stream_health
    from .models import StrategySignal, StrategyTarget
    latest_signal=StrategySignal.objects.filter(strategy_instance_id=OuterRef("pk")).order_by("-signal_time","-id")
    latest_target=StrategyTarget.objects.filter(strategy_instance_id=OuterRef("pk"),status="ACTIVE").order_by("-created_at","-id")
    attributed=StrategyAttributedPosition.objects.filter(strategy_instance_id=OuterRef("pk"),
        instrument_id=OuterRef("instrument_id"),portfolio_id=OuterRef("portfolio_id"))
    active_attribution=OrderIntentAttribution.objects.filter(strategy_instance_id=OuterRef("pk"),
        order_intent__order__status__in=["CREATED","RISK_APPROVED","QUEUED","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED"]
        ).order_by("-order_intent__order__created_at")
    last_fill=Fill.objects.filter(order__intent__attributions__strategy_instance_id=OuterRef("pk")).order_by("-executed_at","-id")
    query=StrategyInstance.objects.select_related(
        "definition","portfolio","instrument__broker_contract","risk_policy","order_policy"
    ).annotate(
        _latest_signal=Subquery(latest_signal.values("signal_type")[:1]),
        _current_target=Subquery(latest_target.values("target_weight")[:1]),
        _attributed_quantity=Subquery(attributed.values("quantity")[:1]),
        _active_order=Subquery(active_attribution.values("order_intent__order__internal_id")[:1]),
        _last_fill=Subquery(last_fill.values("execution_id")[:1]),
    )
    if detail:
        query=query.prefetch_related(
            Prefetch("versions",queryset=StrategyVersion.objects.order_by("-version")),
            Prefetch("input_bindings",queryset=StrategyInputBinding.objects.select_related("requirement","strategy_version")),
        )
    return annotate_stream_health(query)


def _instance(item, detail=False):
    from apps.market_streams.models import IndicatorValue, MarketBar
    contract=getattr(item.instrument,"broker_contract",None)
    plugin=get_plugin(item.definition)
    annotated=hasattr(item,"_current_target")
    latest_bar_at=getattr(item,"_stream_last_final_bar",None)
    if not getattr(item,"_stream_annotated",False):
        latest_bar=MarketBar.objects.filter(instrument=item.instrument,interval=item.timeframe,is_final=True).order_by("-window_end","-version").first()
        latest_bar_at=latest_bar.window_end if latest_bar else None
    latest_signal=getattr(item,"_latest_signal",None) if annotated else item.signals.order_by("-signal_time").values_list("signal_type",flat=True).first()
    latest_target=getattr(item,"_current_target",None) if annotated else item.targets.order_by("-created_at").values_list("target_weight",flat=True).first()
    attributed=getattr(item,"_attributed_quantity",None) if annotated else item.attributed_positions.filter(
        instrument=item.instrument,portfolio=item.portfolio).values_list("quantity",flat=True).first()
    active_order=getattr(item,"_active_order",None) if annotated else item.orderintentattribution_set.filter(
        order_intent__order__status__in=["CREATED","RISK_APPROVED","QUEUED","SUBMITTED","ACKNOWLEDGED","PARTIALLY_FILLED"]
        ).values_list("order_intent__order__internal_id",flat=True).first()
    last_fill=getattr(item,"_last_fill",None)
    latest_indicators={}
    from apps.market_streams.health import strategy_stream_status
    bindings=[binding for binding in item.input_bindings.all()
        if binding.strategy_version.version==item.version and binding.requirement.input_type=="INDICATOR"] if detail else []
    if bindings:
        values={}
        for value in IndicatorValue.objects.filter(instrument=item.instrument,timeframe=item.timeframe,
                parameters_hash__in=[binding.requirement.parameters_hash for binding in bindings],is_final=True
                ).order_by("parameters_hash","-event_time","-id"):
            values.setdefault(value.parameters_hash,value)
        from apps.market_streams.services import _indicator_output_name
        latest_indicators={_indicator_output_name(binding.requirement):values[binding.requirement.parameters_hash].value
            for binding in bindings if binding.requirement.parameters_hash in values}
    row={"id":item.pk,"name":item.name,"definition_key":item.definition.key,"definition_name":item.definition.name,
        "portfolio_id":item.portfolio_id,"portfolio":item.portfolio.name,"instrument_id":item.instrument_id,
        "symbol":item.instrument.symbol,"asset_class":item.instrument.asset_class,"exchange":item.instrument.exchange,
        "currency":item.instrument.currency,"conid":contract.conid if contract else None,
        "primary_exchange":contract.primary_exchange if contract else None,"timeframe":item.timeframe,
        "parameters":item.parameters,"target_configuration":item.target_configuration,"risk_policy_id":item.risk_policy_id,
        "order_policy_id":item.order_policy_id,"execution_mode":item.execution_mode,"state":item.state,"enabled":item.enabled,
        "version":item.version,"warmup_progress":item.warmup_progress,"warmup_required":plugin.warmup_bars(item.parameters),
        "warmup_started_at":item.warmup_started_at,"warmup_last_progress_at":item.warmup_last_progress_at,
        "block_reason":item.block_reason,"effective_from":item.effective_from,"effective_to":item.effective_to,
        "last_final_bar":latest_bar_at,"latest_indicators":latest_indicators,
        "latest_signal":latest_signal,"current_target":latest_target,
        "attributed_quantity":attributed or 0,
        "active_order":active_order,
        "last_fill":last_fill,"cooldown":item.state_data.get("cooldown_until"),
        "streaming":strategy_stream_status(item),"created_at":item.created_at,"updated_at":item.updated_at}
    if detail:
        row["versions"]=[{"id":x.pk,"version":x.version,"parameter_hash":x.parameter_hash,"configuration_snapshot":x.configuration_snapshot,
            "created_at":x.created_at,"activated_at":x.activated_at,"retired_at":x.retired_at} for x in item.versions.all()]
        row["requirements"]=[{"identity_hash":b.requirement.identity_hash,"input_type":b.requirement.input_type,
            "name":b.requirement.name,"parameters":b.requirement.parameters,"parameters_hash":b.requirement.parameters_hash,
            "warmup_bars":b.requirement.warmup_bars,"shared_by":b.requirement.active_ref_count,"active":b.active}
            for b in item.input_bindings.all() if b.strategy_version.version==item.version]
    return row


def _get(pk):
    return _strategy_queryset(detail=True).get(pk=pk)


def _request_actor(request):
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        return user.get_username()
    return "frontend_operator"


@csrf_exempt
def instances(request, instance_id=None):
    try:
        if request.method == "GET":
            if instance_id:return response(_instance(_get(instance_id),True))
            query=_strategy_queryset()
            for field,param in [("portfolio_id","portfolio"),("instrument__symbol","ticker"),("definition__key","strategy_type"),("state","state"),("execution_mode","execution_mode")]:
                if request.GET.get(param):query=query.filter(**{field:request.GET[param]})
            return response([_instance(x) for x in query.order_by("name")])
        try:
            payload=json.loads(request.body or b"{}")
        except json.JSONDecodeError:
            error=StrategyDeletionError("INVALID_STRATEGY_DELETE_REQUEST","Request body must be valid JSON",status=400)
            if request.method=="DELETE" and instance_id:
                audit_strategy_deletion_rejection(instance_id,attempt_key=request.headers.get("Idempotency-Key"),
                    actor=_request_actor(request),error=error)
                raise error
            raise ValueError("Request body must be valid JSON")
        if request.method == "DELETE" and instance_id:
            result=delete_strategy_instance(instance_id,payload.get("strategy_name"),
                attempt_key=request.headers.get("Idempotency-Key"),actor=_request_actor(request))
            return response(result)
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
            updated=update_instance(item,changes)
            return response(_instance(_get(updated.pk),True))
        return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"Unsupported method","details":{}})
    except StrategyDeletionError as exc:
        return response(status=exc.status,error={"code":exc.code,"message":str(exc),"details":exc.details})
    except (KeyError,ValueError,IntegrityError,StrategyInstance.DoesNotExist,StrategyDefinition.DoesNotExist,
            TradingPortfolio.DoesNotExist,StrategyRiskPolicy.DoesNotExist,OrderPolicy.DoesNotExist,Instrument.DoesNotExist) as exc:
        status=404 if isinstance(exc,StrategyInstance.DoesNotExist) else 400
        return response(status=status,error={"code":"INVALID_STRATEGY_INSTANCE","message":str(exc),"details":{}})


@csrf_exempt
def action(request, instance_id, action_name):
    if request.method!="POST":return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"POST required","details":{}})
    key=request.headers.get("Idempotency-Key")
    if not key:return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    try:
        item=_get(instance_id);payload=json.loads(request.body or b"{}")
        if action_name not in {"enable","pause","evaluate","flatten"}:
            return response(status=404,error={"code":"NOT_FOUND","message":"Unknown action","details":{}})
        request_hash=canonical_request_hash("strategy_action",{"strategy_instance_id":instance_id,"action":action_name,"payload":payload})
        retry_requested=request.headers.get("Idempotency-Retry","").strip().lower() in {"1","true","yes"}
        with transaction.atomic():
            operation,created=StrategyAction.objects.select_for_update().get_or_create(idempotency_key=key,defaults={
                "strategy_instance":item,"action":action_name,"request_hash":request_hash})
            if not created:
                require_matching_request(operation.request_hash,request_hash)
                if operation.status=="COMPLETED":
                    if operation.result.get("run_id"):
                        run=StrategyRun.objects.get(pk=operation.result["run_id"])
                        return response({"id":run.pk,"status":run.status,"error":run.error,
                            "target_ids":list(run.targets.values_list("pk",flat=True))},status=200)
                    return response(_instance(_get(instance_id),True),status=200)
                if operation.status=="PROCESSING":
                    return response({"action_id":operation.pk,"status":operation.status},status=202)
                if not retry_requested or not operation.retryable:
                    return response(status=409,error={"code":"RETRY_NOT_ALLOWED","message":operation.last_error or "Strategy action is not retryable","details":{}})
                operation.status="PROCESSING";operation.last_error="";operation.retryable=False
                operation.attempt_count+=1;operation.completed_at=None
                operation.save(update_fields=["status","last_error","retryable","attempt_count","completed_at"])
        if action_name=="enable":
            item=enable_instance(item)
            StrategyAction.objects.filter(pk=operation.pk).update(status="COMPLETED",result={"strategy_instance_id":item.pk},
                completed_at=timezone.now(),last_error="",retryable=False)
            return response(_instance(_get(item.pk),True))
        if action_name=="pause":
            item=pause_instance(item)
            StrategyAction.objects.filter(pk=operation.pk).update(status="COMPLETED",result={"strategy_instance_id":item.pk},
                completed_at=timezone.now(),last_error="",retryable=False)
            return response(_instance(_get(item.pk),True))
        if action_name in {"evaluate","flatten"}:
            if action_name=="flatten":
                run=flatten_instance(item,event_id=payload.get("event_id"))
            else:
                run=evaluate_instance(item,bar=payload.get("bar",{"is_final":True}),indicators=payload.get("indicators",{}),
                    previous_indicators=payload.get("previous_indicators",{}),event_id=payload.get("event_id"),
                    source_data_version=int(payload.get("source_data_version",1)),force=bool(payload.get("force",False)),
                    retry_failed=retry_requested)
            if run.status=="ERROR":raise RuntimeError(run.error or "Strategy evaluation failed")
            if action_name=="flatten" and payload.get("reason"):
                from apps.audit.models import AuditEvent
                AuditEvent.objects.get_or_create(idempotency_key=f"audit:strategy:{item.pk}:flatten:{run.pk}",defaults={
                    "event_type":"strategy.flatten.requested","actor":"frontend_operator","aggregate_type":"strategy_instance",
                    "aggregate_id":str(item.pk),"data":{"reason":payload["reason"],"strategy_run_id":run.pk}})
            result={"run_id":run.pk}
            StrategyAction.objects.filter(pk=operation.pk).update(status="COMPLETED",result=result,
                completed_at=timezone.now(),last_error="",retryable=False)
            return response({"id":run.pk,"status":run.status,"error":run.error,"target_ids":list(run.targets.values_list("pk",flat=True))},status=201)
    except IdempotencyConflict as exc:
        return response(status=409,error={"code":"IDEMPOTENCY_CONFLICT","message":str(exc),"details":{}})
    except (ValueError,StrategyInstance.DoesNotExist) as exc:
        if "operation" in locals():
            StrategyAction.objects.filter(pk=operation.pk).update(status="FAILED",last_error=str(exc)[:1000],
                retryable=False,completed_at=timezone.now())
        return response(status=400,error={"code":"STRATEGY_ACTION_FAILED","message":str(exc),"details":{}})
    except Exception as exc:
        if "operation" in locals():
            StrategyAction.objects.filter(pk=operation.pk).update(status="FAILED",last_error=str(exc)[:1000],
                retryable=True,completed_at=timezone.now())
        return response(status=503,error={"code":"STRATEGY_ACTION_FAILED","message":str(exc),"details":{"retryable":True}})


def related(request, instance_id, resource):
    invalid=method_guard(request,"GET")
    if invalid:return invalid
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
        for attribution in item.orderintentattribution_set.select_related("order_intent__order").all():
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
    invalid=method_guard(request,"GET")
    if invalid:return invalid
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
    for attribution in item.orderintentattribution_set.select_related("order_intent__order").all():
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
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    return response({"risk_policies":[{"id":x.pk,"name":x.name,"maximum_weight":x.maximum_weight,"maximum_notional":x.maximum_notional,
        "maximum_quantity":x.maximum_quantity,"allow_short":x.allow_short} for x in StrategyRiskPolicy.objects.filter(enabled=True)],
        "order_policies":[{"id":x.pk,"name":x.name,"order_type":x.order_type,"time_in_force":x.time_in_force,
        "limit_offset_bps":x.limit_offset_bps,"price_collar_bps":x.price_collar_bps,"allow_market_order":x.allow_market_order,
        "replace_after_seconds":x.replace_after_seconds,"maximum_replacements":x.maximum_replacements,
        "cancel_at_session_end":x.cancel_at_session_end,"outside_regular_hours":x.outside_regular_hours} for x in OrderPolicy.objects.filter(enabled=True)]})


@csrf_exempt
def resolve(request):
    invalid=method_guard(request,"GET","POST")
    if invalid:return invalid
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
    invalid=method_guard(request,"GET")
    if invalid:return invalid
    try:return response(search_broker_instruments(request.GET.get("query")))
    except Exception as exc:return response(status=502,error={"code":"INSTRUMENT_SEARCH_FAILED","message":str(exc),"details":{}})
