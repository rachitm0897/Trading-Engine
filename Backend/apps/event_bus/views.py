from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.http import HttpResponse
from apps.core.views import response, _serialize
from .models import DeadLetterEvent, ReplayRequest, StreamHealthMetric


def health(request):
    from apps.audit.models import OutboxEvent
    from apps.market_streams.models import InstrumentMarketState
    metrics = _serialize(StreamHealthMetric.objects.all(), ["component","metric","status","value","observed_at"])
    flink = {"status":"UNKNOWN"}
    try:
        import requests
        value = requests.get(settings.FLINK_REST_URL + "/jobs/overview", timeout=2).json()
        flink = {"status":"HEALTHY", "jobs": value.get("jobs", [])}
    except Exception as exc:
        flink = {"status":"DEGRADED" if settings.KAFKA_ENABLED else "DISABLED", "error":str(exc)[:120]}
    return response({"kafka_enabled":settings.KAFKA_ENABLED,"metrics":metrics,"flink":flink,
        "outbox_pending":OutboxEvent.objects.exclude(status="PUBLISHED").count(),
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
