from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from apps.core.views import response, _serialize
from .models import DeadLetterEvent, ReplayRequest, StreamHealthMetric


def health(request):
    from apps.audit.models import OutboxEvent
    from apps.market_streams.models import InstrumentMarketState
    metric_objects=list(StreamHealthMetric.objects.all())
    metrics = _serialize(metric_objects, ["component","metric","status","value","observed_at"])
    heartbeat=next((item for item in metric_objects if item.component=="backend-market-consumer" and item.metric=="heartbeat"),None)
    consumer={"status":"UNKNOWN","last_heartbeat":None,"value":{}}
    if heartbeat:
        age=(timezone.now()-heartbeat.observed_at).total_seconds()
        status=heartbeat.status if age<=settings.MARKET_CONSUMER_HEARTBEAT_STALE_SECONDS else "STALE"
        consumer={"status":status,"last_heartbeat":heartbeat.observed_at,"age_seconds":round(age,1),"value":heartbeat.value}
        for row in metrics:
            if row["component"]=="backend-market-consumer" and row["metric"]=="heartbeat":row["status"]=status
    flink = {"status":"UNKNOWN"}
    try:
        import requests
        value = requests.get(settings.FLINK_REST_URL + "/jobs/overview", timeout=2).json()
        jobs=value.get("jobs",[])
        flink = {"status":"HEALTHY" if jobs and all(job.get("state")=="RUNNING" for job in jobs) else "DEGRADED", "jobs": jobs}
    except Exception as exc:
        flink = {"status":"DEGRADED" if settings.KAFKA_ENABLED else "DISABLED", "error":str(exc)[:120]}
    from apps.strategies.models import StrategyInstance
    from apps.market_streams.health import strategy_stream_status
    strategies=[strategy_stream_status(item) for item in StrategyInstance.objects.filter(enabled=True).select_related(
        "definition","instrument__broker_contract").order_by("name")]
    gateway_metric=next((item for item in metric_objects if item.component=="gateway" and item.metric=="connectivity"),None)
    gateway={"status":gateway_metric.status if gateway_metric else "UNKNOWN",
        "value":gateway_metric.value if gateway_metric else {},"observed_at":gateway_metric.observed_at if gateway_metric else None}
    kafka_metric=next((item for item in metric_objects if item.component=="kafka" and item.metric=="connectivity"),None)
    lag_metric=next((item for item in metric_objects if item.component=="backend-market-consumer" and item.metric=="topic_lag"),None)
    reasons=[]
    if not settings.KAFKA_ENABLED:reasons.append("Kafka is disabled")
    elif not kafka_metric or kafka_metric.status!="HEALTHY":reasons.append("Kafka connectivity is not healthy")
    if gateway["status"]!="HEALTHY":reasons.append("Gateway is not connected and reconciled")
    if flink["status"]!="HEALTHY":reasons.append("One or more Flink jobs are not running")
    if consumer["status"]!="HEALTHY":reasons.append("Backend market consumer heartbeat is not healthy")
    if lag_metric and lag_metric.status=="DEGRADED":reasons.append("Kafka consumer lag exceeds the configured threshold")
    broken=[item for item in strategies if item["status"]!="HEALTHY"]
    if broken:reasons.append(f"{len(broken)} active strategy data path(s) are not healthy")
    outbox_pending=OutboxEvent.objects.exclude(status="PUBLISHED").count()
    outbox_failed=OutboxEvent.objects.filter(status="FAILED").count()
    if outbox_failed:reasons.append(f"{outbox_failed} outbox event(s) failed publication")
    data_path_status="DISABLED" if not settings.KAFKA_ENABLED else ("HEALTHY" if not reasons else "DEGRADED")
    return response({"kafka_enabled":settings.KAFKA_ENABLED,"data_path_status":data_path_status,
        "data_path_reasons":reasons,"gateway":gateway,"consumer":consumer,"metrics":metrics,"flink":flink,
        "strategies":strategies,"outbox_pending":outbox_pending,"outbox_failed":outbox_failed,
        "dead_letter_count":DeadLetterEvent.objects.count(),
        "stale_instrument_count":InstrumentMarketState.objects.exclude(status="FRESH").count()})


def prometheus_metrics(request):
    from prometheus_client import CollectorRegistry, Gauge, generate_latest, CONTENT_TYPE_LATEST
    from apps.audit.models import OutboxEvent
    from apps.market_streams.models import InstrumentMarketState
    registry=CollectorRegistry()
    Gauge("finflock_outbox_pending","Outbox events awaiting Kafka",registry=registry).set(OutboxEvent.objects.exclude(status="PUBLISHED").count())
    Gauge("finflock_dead_letter_total","Persisted dead-letter events",registry=registry).set(DeadLetterEvent.objects.count())
    Gauge("finflock_stale_instruments","Stale or unavailable instruments",registry=registry).set(InstrumentMarketState.objects.exclude(status="FRESH").count())
    return HttpResponse(generate_latest(registry),content_type=CONTENT_TYPE_LATEST)


def topics(request):
    from pathlib import Path
    import json
    path = Path(settings.BASE_DIR).parent / "streaming" / "kafka" / "topics.yml"
    data = json.loads(path.read_text()) if path.exists() else {"topics":[]}
    return response(data.get("topics", []))


def consumer_lag(request):
    metrics = StreamHealthMetric.objects.filter(metric__icontains="lag")
    return response(_serialize(metrics,["component","metric","status","value","observed_at"]))


def dead_letter(request):
    return response(_serialize(DeadLetterEvent.objects.order_by("-created_at")[:250],
        ["event_id","source_topic","consumer_name","reason","envelope","replayed_at","created_at"]))


@csrf_exempt
def replay(request):
    if request.method != "POST": return response(status=405,error={"code":"METHOD_NOT_ALLOWED","message":"POST required","details":{}})
    import json
    key=request.headers.get("Idempotency-Key")
    if not key:return response(status=400,error={"code":"IDEMPOTENCY_KEY_REQUIRED","message":"Idempotency-Key header is required","details":{}})
    payload=json.loads(request.body or b"{}")
    from .services import request_replay
    item=request_replay(payload["topic"],payload["consumer_name"],key,payload.get("from_timestamp"),payload.get("to_timestamp"))
    if item.status=="REQUESTED":
        from .tasks import execute_replay_request
        execute_replay_request.delay(item.pk)
    return response({"id":item.pk,"status":item.status},status=202)
