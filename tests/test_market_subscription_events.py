import pytest
import responses
from datetime import timedelta
from django.utils import timezone
from apps.audit.models import OutboxEvent
from apps.broker_gateway.sync import process_snapshot
from apps.instruments.models import BrokerContract,Instrument
from apps.market_streams.models import MarketDataSubscription
from apps.event_bus.models import StreamHealthMetric
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


def test_async_ibkr_market_error_blocks_strategy_with_exact_reason():
    account=BrokerAccount.objects.create(account_id="DU-PERMISSION");portfolio=TradingPortfolio.objects.create(name="Permission",account=account)
    instrument=Instrument.objects.create(symbol="PERM",exchange="SMART",currency="USD");BrokerContract.objects.create(instrument=instrument,conid=780)
    instance,_=create_instance(name="Permission failure",definition_key="FIXED_WEIGHT_REBALANCE",portfolio=portfolio,
        instrument_id=instrument.pk,timeframe="1m",parameters={"direction":"LONG"},target_configuration={"target_weight":"0.01"},qualify=False)
    enable_instance(instance);MarketDataSubscription.objects.create(instrument=instrument,conid=780,timeframe="1m",consumer_count=1,state="ACTIVE")
    process_snapshot({"event_type":"market.error","payload":{"subscription_key":f"{instrument.pk}:1m",
        "error_code":"354","error_message":"Requested market data is not subscribed"}})
    instance.refresh_from_db();subscription=MarketDataSubscription.objects.get(instrument=instrument,timeframe="1m")
    assert subscription.state=="ERROR" and subscription.last_error=="IBKR error 354: Requested market data is not subscribed"
    assert instance.state=="BLOCKED" and instance.block_reason==subscription.last_error


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


@responses.activate
def test_stream_health_is_not_green_when_consumer_heartbeat_is_stale(client,settings):
    settings.KAFKA_ENABLED=True;settings.MARKET_CONSUMER_HEARTBEAT_STALE_SECONDS=30
    responses.get(settings.FLINK_REST_URL+"/jobs/overview",json={"jobs":[{"id":"normalizer","state":"RUNNING"}]})
    StreamHealthMetric.objects.create(component="kafka",metric="connectivity",status="HEALTHY",value={"topics":8})
    StreamHealthMetric.objects.create(component="gateway",metric="connectivity",status="HEALTHY",
        value={"connected":True,"reconciled":True})
    heartbeat=StreamHealthMetric.objects.create(component="backend-market-consumer",metric="heartbeat",status="HEALTHY",value={})
    StreamHealthMetric.objects.create(component="backend-market-consumer",metric="topic_lag",status="HEALTHY",value={"total":0})
    StreamHealthMetric.objects.filter(pk=heartbeat.pk).update(observed_at=timezone.now()-timedelta(minutes=2))
    data=client.get("/api/v1/streaming/health/").json()["data"]
    assert data["consumer"]["status"]=="STALE" and data["data_path_status"]=="DEGRADED"
    assert "Backend market consumer heartbeat is not healthy" in data["data_path_reasons"]


def test_strategy_api_exposes_each_persisted_stream_stage(client):
    account=BrokerAccount.objects.create(account_id="DU-HEALTH");portfolio=TradingPortfolio.objects.create(name="Health",account=account)
    instrument=Instrument.objects.create(symbol="PATH",exchange="SMART",currency="USD");BrokerContract.objects.create(instrument=instrument,conid=779)
    instance,_=create_instance(name="Path health",definition_key="FIXED_WEIGHT_REBALANCE",portfolio=portfolio,
        instrument_id=instrument.pk,timeframe="1m",parameters={"direction":"LONG"},target_configuration={"target_weight":"0.01"},qualify=False)
    enable_instance(instance)
    MarketDataSubscription.objects.create(instrument=instrument,conid=779,timeframe="1m",consumer_count=1,state="ACTIVE",
        last_event_at=timezone.now())
    now=timezone.now()
    from apps.market_streams.models import MarketBar
    from apps.strategies.framework import evaluate_instance
    MarketBar.objects.create(instrument=instrument,bar_id="path-final",interval="1m",window_start=now-timedelta(minutes=1),
        window_end=now,open=1,high=1,low=1,close=1,volume=1,is_final=True,produced_at=now)
    evaluate_instance(instance,bar={"bar_id":"path-final","close":"1","is_final":True},indicators={},event_id="path-final:1")
    stream=client.get(f"/api/v1/strategy-instances/{instance.pk}/").json()["data"]["streaming"]
    assert stream["subscription_state"]=="ACTIVE" and stream["conid"]==779
    assert stream["last_raw_event"] and stream["last_canonical_event"] and stream["last_final_bar"]
    assert stream["last_strategy_run"] and stream["status"]=="HEALTHY"
