import uuid
from decimal import Decimal
import pytest
from django.test import override_settings
from apps.audit.models import OutboxEvent
from apps.event_bus.models import ConsumedEvent, DeadLetterEvent, ReplayRequest
from apps.event_bus.schemas import decimal_safe, validate_envelope
from apps.event_bus.services import consume_once, envelope_for, publish_batch, replay_envelopes, route_dead_letter

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


def test_duplicate_consumer_is_idempotent():
    envelope=envelope_for(event()); calls=[]
    assert consume_once("bars",envelope,lambda x:calls.append(x) or {"ok":True})=={"ok":True}
    assert consume_once("bars",envelope,lambda x:calls.append(x))=={"duplicate":True}
    assert len(calls)==1 and ConsumedEvent.objects.count()==1


def test_dead_letter_retains_original_event():
    envelope=envelope_for(event()); route_dead_letter("market.raw.v1",envelope,"malformed","normalizer")
    row=DeadLetterEvent.objects.get(); assert row.envelope["event_id"]==envelope["event_id"] and row.reason=="malformed"


def test_replay_uses_consumer_idempotency():
    request=ReplayRequest.objects.create(topic="market.bars.v1",consumer_name="rebuild-bars",idempotency_key="replay-1")
    values=[envelope_for(event("replay-event"))];calls=[]
    replay_envelopes(request,values,lambda name,item:consume_once(name,item,lambda x:calls.append(x)))
    request.refresh_from_db();assert request.status=="COMPLETED" and request.processed_count==1 and len(calls)==1
