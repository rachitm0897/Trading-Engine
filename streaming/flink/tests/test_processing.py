from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest
from streaming.flink.jobs.events import envelope
from streaming.flink.jobs.identity import (
    bar_event_key,
    canonical_event_key,
    deterministic_event_id,
    indicator_event_key,
    market_quality_event_key,
    raw_event_key,
    requirement_identity_hash,
    starting_offset_policy,
)
from streaming.flink.jobs.processing import (
    advance_bar_version,
    aggregate_bars,
    buffer_unknown_registry_event,
    compute_indicators,
    normalize_market_event,
    partition_expired_registry_events,
    quality_state,
)


def test_normalization_and_validation():
    out=normalize_market_event({"source_event_id":"1","symbol":"AAPL","event_time":"2026-01-01T00:00:01Z","price":"10.5","volume":"2"},{"AAPL":7})
    assert out["instrument_id"]=="7" and out["price"]=="10.5"
    with pytest.raises(ValueError):normalize_market_event({"symbol":"BAD"},{})
    bar=normalize_market_event({"source_event_id":"bar-1","instrument_id":7,"conid":99,"symbol":"AAPL","event_kind":"BAR",
        "timeframe":"1m","event_time":"2026-01-01T00:00:00Z","window_start":"2026-01-01T00:00:00Z",
        "window_end":"2026-01-01T00:01:00Z","open":"10","high":"12","low":"9","close":"11","volume":"5"},{})
    assert bar["event_kind"]=="BAR" and bar["instrument_id"]=="7" and bar["price"]=="11"
    mapped=normalize_market_event({"source_event_id":"2","conid":99,"symbol":"AAPL","event_time":"2026-01-01T00:00:01Z","price":"10"},{"99":7})
    assert mapped["instrument_id"]=="7"


def test_event_time_ohlcv_and_corrected_version():
    ticks=[{"source_event_id":"2","instrument_id":"1","event_time":"2026-01-01T00:00:20Z","price":"12","volume":"3"},
           {"source_event_id":"1","instrument_id":"1","event_time":"2026-01-01T00:00:10Z","price":"10","volume":"2"}]
    first=aggregate_bars(ticks)[0]; corrected=aggregate_bars(ticks,prior_versions={first["bar_id"]:first["version"]})[0]
    assert (first["open"],first["high"],first["low"],first["close"],first["volume"])==("10","12","10","12","5")
    assert corrected["bar_id"]==first["bar_id"] and corrected["version"]==2
    sub_bars=[{"source_event_id":"a","instrument_id":"1","event_time":"2026-01-01T00:00:00Z","price":"11","open":"10","high":"12","low":"9","close":"11","volume":"2"},
        {"source_event_id":"b","instrument_id":"1","event_time":"2026-01-01T00:00:05Z","price":"13","open":"11","high":"14","low":"10","close":"13","volume":"3"}]
    combined=aggregate_bars(sub_bars)[0]
    assert (combined["open"],combined["high"],combined["low"],combined["close"],combined["volume"])==("10","14","9","13","5")


def test_indicators_and_stale_transitions():
    bars=[]
    for i in range(60):
        value=Decimal(100+i)
        bars.append({"window_end":f"2026-01-01T00:{i:02d}:00+00:00","open":str(value),"high":str(value+1),"low":str(value-1),"close":str(value),"volume":str(1000+i),"is_final":True})
    values=compute_indicators(bars)
    assert all(values[key] is not None for key in ["sma_fast","sma_slow","rsi","donchian_upper","momentum","realized_volatility","average_volume","reference_price"])
    now=datetime.now(timezone.utc);assert quality_state(None,now,30)=="UNAVAILABLE"
    assert quality_state(now,now,30)=="FRESH" and quality_state(now-timedelta(seconds=31),now,30)=="STALE"


def test_finnhub_provenance_survives_canonical_normalization():
    generation="12345678-1234-5678-1234-567812345678"
    raw={"source_event_id":"finnhub-window","subscription_key":"7:1m","instrument_id":7,
        "conid":265598,"symbol":"AAPL","event_kind":"BAR","timeframe":"5s",
        "event_time":"2026-07-15T00:00:00+00:00","window_start":"2026-07-15T00:00:00+00:00",
        "window_end":"2026-07-15T00:00:05+00:00","open":"100","high":"102","low":"99",
        "close":"101","volume":"12","source":"finnhub_live","provider":"FINNHUB",
        "provider_symbol":"AAPL","provider_generation":generation,"fallback_reason":"IBKR_TIMEOUT"}
    normalized=normalize_market_event(raw,{})
    assert normalized["instrument_id"]=="7" and normalized["conid"]==265598
    assert normalized["provider"]=="FINNHUB" and normalized["provider_generation"]==generation
    assert normalized["source"]=="finnhub_live" and normalized["fallback_reason"]=="IBKR_TIMEOUT"


def test_equivalent_ibkr_and_finnhub_inputs_produce_the_same_canonical_ohlcv():
    base={"subscription_key":"7:1m","instrument_id":7,"conid":265598,"symbol":"AAPL",
        "event_kind":"BAR","timeframe":"5s","event_time":"2026-07-15T00:00:00+00:00",
        "window_start":"2026-07-15T00:00:00+00:00","window_end":"2026-07-15T00:00:05+00:00",
        "open":"100","high":"102","low":"99","close":"101","volume":"12",
        "provider_generation":"12345678-1234-5678-1234-567812345678"}
    ibkr=normalize_market_event({**base,"source_event_id":"ibkr","source":"ibkr_live","provider":"IBKR"},{})
    finnhub=normalize_market_event({**base,"source_event_id":"finnhub","source":"finnhub_live","provider":"FINNHUB",
        "provider_symbol":"AAPL"},{})
    ibkr_bar=aggregate_bars([ibkr],"1m",60)[0]
    finnhub_bar=aggregate_bars([finnhub],"1m",60)[0]
    for field in ("bar_id","instrument_id","interval","window_start","window_end","open","high","low","close","volume"):
        assert ibkr_bar[field]==finnhub_bar[field]


def test_registry_event_after_raw_event_releases_bounded_event():
    raw={"source_event_id":"late-registry","conid":123,"symbol":"LATE","event_time":"2026-01-01T00:00:01Z",
        "price":"10","provider":"IBKR","provider_generation":"generation-1"}
    incoming={"event_id":"raw-envelope","payload":raw}
    pending,overflow=buffer_unknown_registry_event([],incoming,expires_at_ms=31_000,maximum_events=2)
    assert len(pending)==1 and overflow==[]
    pending,overflow=buffer_unknown_registry_event(pending,incoming,expires_at_ms=31_001,maximum_events=2)
    assert len(pending)==1 and overflow==[]
    normalized=normalize_market_event({**pending[0]["event"]["payload"],"instrument_id":77},{})
    assert normalized["instrument_id"]=="77"
    remaining,expired=partition_expired_registry_events(pending,30_999)
    assert len(remaining)==1 and expired==[]
    remaining,expired=partition_expired_registry_events(pending,31_000)
    assert remaining==[] and len(expired)==1


def test_checkpoint_replay_reuses_every_derived_identity():
    raw={"source_event_id":"checkpoint-source","provider":"IBKR","provider_generation":"generation-1"}
    raw_key=raw_event_key(raw)
    raw_id=deterministic_event_id("market.raw",raw_key)
    canonical_key=canonical_event_key(raw_key,"42")
    first=envelope("market.canonical","instrument","42",{"value":1},canonical_key,{"event_id":raw_id})
    restored=envelope("market.canonical","instrument","42",{"value":1},canonical_key,{"event_id":raw_id})
    assert first["event_id"]==restored["event_id"]
    assert bar_event_key("bar-id",2)==bar_event_key("bar-id",2)
    assert indicator_event_key("bar-id",2,"a"*64,1)==indicator_event_key("bar-id",2,"a"*64,1)
    assert market_quality_event_key("checkpoint-source","STALE")==market_quality_event_key("checkpoint-source","STALE")


def test_checkpointed_bar_content_does_not_create_a_new_correction_version():
    bar=aggregate_bars([{
        "source_event_id":"checkpoint-tick",
        "instrument_id":"42",
        "event_time":"2026-01-01T00:00:01Z",
        "price":"100",
        "volume":"1",
    }])[0]
    checkpointed,version=advance_bar_version({},bar)
    assert version==1
    restored,version=advance_bar_version(checkpointed,dict(bar))
    assert restored==checkpointed and version is None
    corrected={**bar,"close":"101","high":"101"}
    _,version=advance_bar_version(restored,corrected)
    assert version==2


def test_full_requirement_identity_prevents_parameter_only_collisions():
    common={"input_type":"INDICATOR","role":"","parameters":{"window":20},"instrument_id":"7",
        "timeframe":"5m","implementation_version":1}
    sma=requirement_identity_hash(name="sma",**common)
    momentum=requirement_identity_hash(name="momentum",**common)
    assert sma!=momentum
    assert requirement_identity_hash(name="sma",**common)==sma


def test_starting_offsets_are_job_configurable_and_default_to_committed():
    assert starting_offset_policy("bar-aggregation-v2")=="committed"
    assert starting_offset_policy("bar-aggregation-v2","latest")=="latest"
    assert starting_offset_policy("bar-aggregation-v2",environment={
        "KAFKA_STARTING_OFFSETS_BAR_AGGREGATION_V2":"earliest",
    })=="earliest"
    with pytest.raises(ValueError):
        starting_offset_policy("bar-aggregation-v2","invalid")


def test_deduplication_state_has_a_configured_ttl():
    from pathlib import Path
    source=Path(__file__).resolve().parents[1]/"jobs"/"market_normalization.py"
    implementation=source.read_text(encoding="utf-8")
    assert "StateTtlConfig" in implementation
    assert "DEDUPLICATION_STATE_TTL_SECONDS" in implementation
