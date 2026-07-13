import pytest
from datetime import timedelta
from django.utils import timezone
from apps.audit.models import OutboxEvent
from apps.broker_gateway.sync import process_snapshot
from apps.instruments.models import BrokerContract,Instrument
from apps.market_streams.models import MarketDataSubscription
from apps.market_streams.tasks import check_warmup_timeouts
from apps.accounts.models import BrokerAccount
from apps.portfolios.models import TradingPortfolio
from apps.strategies.framework import create_instance,enable_instance

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


def test_stalled_warmup_becomes_visibly_blocked(settings):
    settings.WARMUP_TIMEOUT_SECONDS=30
    account=BrokerAccount.objects.create(account_id="DU-WARMUP");portfolio=TradingPortfolio.objects.create(name="Warmup",account=account)
    instrument=Instrument.objects.create(symbol="STALL",exchange="SMART",currency="USD");BrokerContract.objects.create(instrument=instrument,conid=778)
    instance,_=create_instance(name="Stalled",definition_key="FIXED_WEIGHT_REBALANCE",portfolio=portfolio,instrument_id=instrument.pk,
        timeframe="1m",parameters={"direction":"LONG"},target_configuration={"target_weight":"0.01"},qualify=False)
    enable_instance(instance);old=timezone.now()-timedelta(minutes=2)
    instance.warmup_started_at=old;instance.warmup_last_progress_at=old;instance.save(update_fields=["warmup_started_at","warmup_last_progress_at"])
    MarketDataSubscription.objects.create(instrument=instrument,conid=778,timeframe="1m",consumer_count=1,state="ERROR",last_error="IBKR error 354: Not subscribed")
    assert check_warmup_timeouts()==1
    instance.refresh_from_db();assert instance.state=="BLOCKED" and "IBKR error 354" in instance.block_reason
