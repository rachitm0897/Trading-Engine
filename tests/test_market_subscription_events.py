import pytest
from apps.audit.models import OutboxEvent
from apps.broker_gateway.sync import process_snapshot
from apps.instruments.models import BrokerContract,Instrument
from apps.market_streams.models import MarketDataSubscription

pytestmark=pytest.mark.django_db


def test_gateway_raw_market_event_enters_transactional_outbox():
    instrument=Instrument.objects.create(symbol="RAW",exchange="SMART",currency="USD")
    BrokerContract.objects.create(instrument=instrument,conid=777)
    subscription=MarketDataSubscription.objects.create(instrument=instrument,conid=777,timeframe="1m",consumer_count=1)
    payload={"source_event_id":"777:1m:2026-07-13T00:00:00+00:00","subscription_key":f"{instrument.pk}:1m",
        "instrument_id":instrument.pk,"conid":777,"symbol":"RAW","timeframe":"1m","event_time":"2026-07-13T00:01:00+00:00"}
    process_snapshot({"event_type":"market.raw","payload":payload});process_snapshot({"event_type":"market.raw","payload":payload})
    subscription.refresh_from_db()
    assert subscription.state=="ACTIVE" and subscription.last_event_at is not None
    assert OutboxEvent.objects.filter(topic="market.raw.v1").count()==1
