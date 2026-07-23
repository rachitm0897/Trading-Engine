import uuid
from datetime import timedelta
from decimal import Decimal
import pytest
from django.test import override_settings
from apps.accounts.models import BrokerAccount
from apps.audit.models import AuditEvent, OutboxEvent
from apps.broker_gateway.models import BrokerPositionSnapshot
from apps.event_bus.models import ConsumedEvent, DeadLetterEvent, ReplayRequest, StreamHealthMetric
from apps.event_bus.schemas import decimal_safe, validate_envelope
from apps.event_bus.services import consume_once, envelope_for, publish_batch, replay_envelopes, route_dead_letter
from apps.event_bus.tasks import compact_operational_records
from django.utils import timezone

pytestmark = pytest.mark.django_db


class Publisher:
    def __init__(self, fail=False): self.fail=fail; self.events=[]
    def publish(self,event):
        if self.fail: raise RuntimeError("kafka down")
        self.events.append(event.event_id)


def event(key="one"):
    return OutboxEvent.objects.create(topic="system.health.v1",aggregate_id="backend",payload={"value":str(Decimal("1.20"))},idempotency_key=key)


def test_envelope_schema_and_decimal_serialization():
    item=event(); envelope=envelope_for(item)
    assert validate_envelope(envelope) and decimal_safe({"x":Decimal("1.20")})=={"x":"1.20"}


@override_settings(KAFKA_ENABLED=True)
def test_outbox_ack_and_retry():
    item=event(); assert publish_batch(Publisher())==1
    item.refresh_from_db(); assert item.status=="PUBLISHED" and item.published_at
    failed=event("two"); assert publish_batch(Publisher(True))==0
    failed.refresh_from_db(); assert failed.status=="FAILED" and failed.attempt_count==1 and "kafka down" in failed.last_error


@override_settings(KAFKA_ENABLED=True)
def test_outbox_produces_a_batch_once_and_preserves_per_event_results():
    first=event("batch-one");second=event("batch-two")
    class BatchPublisher:
        calls=0
        def publish_batch(self,events):
            self.calls+=1
            return {item.pk:("broker rejected" if item.pk==second.pk else "") for item in events}
    publisher=BatchPublisher()
    assert publish_batch(publisher)==1 and publisher.calls==1
    first.refresh_from_db();second.refresh_from_db()
    assert first.status=="PUBLISHED" and first.published_at is not None
    assert second.status=="FAILED" and second.published_at is None and "broker rejected" in second.last_error


def test_duplicate_consumer_is_idempotent():
    envelope=envelope_for(event()); calls=[]
    assert consume_once("bars",envelope,lambda x:calls.append(x) or {"ok":True})=={"ok":True}
    assert consume_once("bars",envelope,lambda x:calls.append(x))=={"duplicate":True}
    assert len(calls)==1 and ConsumedEvent.objects.count()==1


def test_failed_consumer_remains_visible_and_can_be_retried():
    envelope=envelope_for(event("failed-consumer"));calls=[]
    def fail_once(value):
        calls.append(value)
        if len(calls)==1:raise RuntimeError("strategy processing exploded")
        return {"ok":True}
    with pytest.raises(RuntimeError,match="strategy processing exploded"):
        consume_once("bars",envelope,fail_once)
    failed=ConsumedEvent.objects.get()
    assert failed.result=={"status":"FAILED","retryable":True,"error":"strategy processing exploded"}
    assert consume_once("bars",envelope,fail_once)=={"ok":True}
    failed.refresh_from_db()
    assert failed.result=={"ok":True} and len(calls)==2


def test_dead_letter_retains_original_event():
    envelope=envelope_for(event()); route_dead_letter("market.raw.v1",envelope,"malformed","normalizer")
    row=DeadLetterEvent.objects.get(); assert row.envelope["event_id"]==envelope["event_id"] and row.reason=="malformed"


def test_replay_uses_consumer_idempotency():
    request=ReplayRequest.objects.create(topic="market.bars.v1",consumer_name="rebuild-bars",idempotency_key="replay-1")
    values=[envelope_for(event("replay-event"))];calls=[]
    replay_envelopes(request,values,lambda name,item:consume_once(name,item,lambda x:calls.append(x)))
    request.refresh_from_db();assert request.status=="COMPLETED" and request.processed_count==1 and len(calls)==1


def test_market_replay_forces_non_live_processing_mode():
    request=ReplayRequest.objects.create(topic="market.bars.v1",consumer_name="safe-replay",idempotency_key="safe-replay")
    values=[envelope_for(event("safe-replay-event"))];calls=[]
    replay_envelopes(request,values,lambda _name,item:calls.append(item))
    assert calls[0]["payload"]["processing_mode"]=="REPLAY"


def test_replay_status_endpoint_is_pollable(client):
    request=ReplayRequest.objects.create(topic="market.bars.v1",consumer_name="poll-replay",idempotency_key="poll-replay")
    body=client.get(f"/api/v1/streaming/replay/{request.pk}/").json()
    assert body["data"]["id"]==request.pk and body["data"]["status"]=="REQUESTED"
    assert client.post(f"/api/v1/streaming/replay/{request.pk}/").status_code==405


@override_settings(OUTBOX_RETENTION_DAYS=1,BROKER_SNAPSHOT_RETENTION_DAYS=1,STREAM_HEALTH_RETENTION_DAYS=1,
    OPERATIONAL_COMPACTION_BATCH_SIZE=100)
def test_compaction_deletes_only_expired_operational_records():
    old=timezone.now()-timedelta(days=2)
    published=event("compact-published");OutboxEvent.objects.filter(pk=published.pk).update(status="PUBLISHED",published_at=old)
    failed=event("compact-failed");OutboxEvent.objects.filter(pk=failed.pk).update(status="FAILED",available_at=old)
    account=BrokerAccount.objects.create(account_id="DU-COMPACT")
    snapshot=BrokerPositionSnapshot.objects.create(broker_account=account,snapshot_key="compact",status="COMPLETED",complete=True)
    BrokerPositionSnapshot.objects.filter(pk=snapshot.pk).update(completed_at=old)
    audit=AuditEvent.objects.create(event_type="immutable",actor="test",aggregate_type="test",aggregate_id="1",
        idempotency_key="audit-immutable")
    metric=StreamHealthMetric.objects.create(component="retired-worker",metric="heartbeat",status="STALE")
    StreamHealthMetric.objects.filter(pk=metric.pk).update(observed_at=old)
    compact_operational_records()
    assert not OutboxEvent.objects.filter(pk=published.pk).exists()
    assert not BrokerPositionSnapshot.objects.filter(pk=snapshot.pk).exists()
    assert OutboxEvent.objects.filter(pk=failed.pk).exists()
    assert not StreamHealthMetric.objects.filter(pk=metric.pk).exists()
    assert AuditEvent.objects.filter(pk=audit.pk).exists()
