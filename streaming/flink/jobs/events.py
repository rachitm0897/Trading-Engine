import uuid
from datetime import datetime, timezone

NAMESPACE=uuid.UUID("8d0ddbee-cd38-49ad-bc36-3c758d8fbd2b")


def payload_of(message):
    return message.get("payload",message)


def envelope(event_type,aggregate_type,aggregate_id,payload,stable_key,source=None,occurred_at=None):
    source=source or {}
    event_id=str(uuid.uuid5(NAMESPACE,f"{event_type}:{stable_key}"))
    now=datetime.now(timezone.utc).isoformat()
    return {"event_id":event_id,"event_type":event_type,"schema_version":1,
        "occurred_at":occurred_at or now,"produced_at":now,"producer":"flink",
        "aggregate_type":aggregate_type,"aggregate_id":str(aggregate_id),
        "correlation_id":source.get("correlation_id") or source.get("event_id") or event_id,
        "causation_id":source.get("event_id"),"idempotency_key":f"{event_type}:{stable_key}","payload":payload}
