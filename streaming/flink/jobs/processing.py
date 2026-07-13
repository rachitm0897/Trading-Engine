import hashlib
import math
from collections import defaultdict, deque
from datetime import datetime, timezone
from decimal import Decimal


def utc(value):
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_market_event(raw, symbol_map):
    kind=raw.get("event_kind","TICK").upper()
    required = ["source_event_id", "symbol", "event_time"] + (["open","high","low","close"] if kind=="BAR" else ["price"])
    missing = [key for key in required if raw.get(key) in (None, "")]
    if missing:
        raise ValueError(f"missing fields: {','.join(missing)}")
    instrument_id = raw.get("instrument_id") or symbol_map.get(str(raw.get("conid"))) or symbol_map.get(raw["symbol"])
    if instrument_id is None:
        raise ValueError("unknown instrument mapping")
    price, volume = Decimal(str(raw.get("price",raw.get("close")))), Decimal(str(raw.get("volume", 0)))
    if price <= 0 or volume < 0:
        raise ValueError("price must be positive and volume non-negative")
    result={"source_event_id": str(raw["source_event_id"]), "instrument_id": str(instrument_id),"conid":raw.get("conid"),
        "symbol": raw["symbol"], "event_time": utc(raw["event_time"]).isoformat(),
        "exchange": raw.get("exchange", "SMART"), "currency": raw.get("currency", "USD"),
        "price": str(price), "volume": str(volume), "source": raw.get("source", "ibkr"),"event_kind":kind}
    if kind=="BAR":
        values={key:Decimal(str(raw[key])) for key in ("open","high","low","close")}
        if min(values.values())<=0 or values["low"]>values["high"]:raise ValueError("invalid OHLC values")
        result.update({key:str(value) for key,value in values.items()})
        result.update({"timeframe":raw["timeframe"],"window_start":utc(raw["window_start"]).isoformat(),
            "window_end":utc(raw["window_end"]).isoformat(),"is_final":bool(raw.get("is_final",True))})
    return result


def window_start(event_time, seconds):
    stamp = int(utc(event_time).timestamp())
    return datetime.fromtimestamp(stamp - stamp % seconds, tz=timezone.utc)


def aggregate_bars(events, interval="1m", seconds=60, prior_versions=None, final=True):
    grouped = defaultdict(list)
    for event in events:
        grouped[(str(event["instrument_id"]), window_start(event["event_time"], seconds))].append(event)
    result = []
    prior_versions = prior_versions or {}
    for (instrument_id, start), ticks in sorted(grouped.items()):
        ticks.sort(key=lambda x: (utc(x["event_time"]), x["source_event_id"]))
        opens=[Decimal(str(x.get("open",x["price"]))) for x in ticks]
        highs=[Decimal(str(x.get("high",x["price"]))) for x in ticks]
        lows=[Decimal(str(x.get("low",x["price"]))) for x in ticks]
        closes=[Decimal(str(x.get("close",x["price"]))) for x in ticks]
        bar_id = hashlib.sha256(f"{instrument_id}:{interval}:{start.isoformat()}".encode()).hexdigest()
        result.append({"bar_id": bar_id, "instrument_id": instrument_id, "interval": interval,
            "window_start": start.isoformat(), "window_end": datetime.fromtimestamp(start.timestamp()+seconds, tz=timezone.utc).isoformat(),
            "open": str(opens[0]), "high": str(max(highs)), "low": str(min(lows)), "close": str(closes[-1]),
            "volume": str(sum(Decimal(str(x.get("volume", 0))) for x in ticks)),
            "source_event_count": len(ticks), "version": prior_versions.get(bar_id, 0) + 1, "is_final": final})
    return result


def _sma(values, n):
    return sum(values[-n:]) / Decimal(n) if len(values) >= n else None


def _rsi(values, n):
    if len(values) <= n:
        return None
    changes = [values[i] - values[i-1] for i in range(len(values)-n, len(values))]
    gains = sum(max(x, Decimal(0)) for x in changes) / Decimal(n)
    losses = sum(max(-x, Decimal(0)) for x in changes) / Decimal(n)
    return Decimal(100) if losses == 0 else Decimal(100) - Decimal(100) / (Decimal(1) + gains/losses)


def compute_indicators(bars, fast=20, slow=50, rsi_period=14, donchian=20, momentum_period=20, volatility_period=20, adv_period=20):
    ordered = sorted((x for x in bars if x.get("is_final", True)), key=lambda x: utc(x["window_end"]))
    closes = [Decimal(x["close"]) for x in ordered]
    highs = [Decimal(x["high"]) for x in ordered]
    lows = [Decimal(x["low"]) for x in ordered]
    volumes = [Decimal(x.get("volume", 0)) for x in ordered]
    if not ordered:
        return {}
    returns = [(closes[i]/closes[i-1])-1 for i in range(1, len(closes)) if closes[i-1] != 0]
    recent_returns = returns[-volatility_period:]
    vol = None
    if len(recent_returns) >= 2:
        mean = sum(recent_returns)/Decimal(len(recent_returns))
        variance = sum((x-mean)**2 for x in recent_returns)/Decimal(len(recent_returns)-1)
        vol = Decimal(str(math.sqrt(float(variance)))) * Decimal(str(math.sqrt(252)))
    return {"sma_fast": _sma(closes, fast), "sma_slow": _sma(closes, slow), "rsi": _rsi(closes, rsi_period),
        "donchian_upper": max(highs[-donchian:]) if len(highs) >= donchian else None,
        "donchian_lower": min(lows[-donchian:]) if len(lows) >= donchian else None,
        "momentum": closes[-1]/closes[-momentum_period-1]-1 if len(closes) > momentum_period and closes[-momentum_period-1] else None,
        "realized_volatility": vol, "average_volume": _sma(volumes, adv_period), "reference_price": closes[-1]}


def compute_indicator(bars, name, parameters):
    """Compute one registry-declared indicator identity, independently of a strategy."""
    ordered = sorted((x for x in bars if x.get("is_final", True)), key=lambda x: utc(x["window_end"]))
    if not ordered:
        return None
    closes=[Decimal(str(x["close"])) for x in ordered];highs=[Decimal(str(x["high"])) for x in ordered]
    lows=[Decimal(str(x["low"])) for x in ordered];volumes=[Decimal(str(x.get("volume",0))) for x in ordered]
    window=int(parameters.get("window",20))
    if name=="rsi":return _rsi(closes,window)
    if name=="sma":return _sma(closes,window)
    if name=="donchian":
        use_upper=parameters.get("side",parameters.get("role","entry")) in {"upper","entry"}
        prior=(highs if use_upper else lows)[:-1]
        if len(prior)<window:return None
        return max(prior[-window:]) if use_upper else min(prior[-window:])
    if name=="momentum":return closes[-1]/closes[-window-1]-1 if len(closes)>window and closes[-window-1] else None
    if name=="realized_volatility":
        returns=[closes[i]/closes[i-1]-1 for i in range(max(1,len(closes)-window),len(closes)) if closes[i-1]]
        if len(returns)<2:return None
        mean=sum(returns)/Decimal(len(returns));variance=sum((x-mean)**2 for x in returns)/Decimal(len(returns)-1)
        return Decimal(str(math.sqrt(float(variance))))*Decimal(str(math.sqrt(252)))
    if name=="average_volume":return _sma(volumes,window)
    if name=="reference_price":return closes[-1]
    raise ValueError(f"unsupported indicator: {name}")


def quality_state(latest_event_at, now, stale_after_seconds):
    if latest_event_at is None:
        return "UNAVAILABLE"
    return "STALE" if (utc(now)-utc(latest_event_at)).total_seconds() > stale_after_seconds else "FRESH"
