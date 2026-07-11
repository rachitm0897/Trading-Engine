from decimal import Decimal, ROUND_DOWN
from math import sqrt

D = Decimal

def _d(value): return value if isinstance(value, Decimal) else Decimal(str(value))
def _cap(value, maximum): return max(-maximum, min(maximum, value))

def fixed_weight(config, series_by_symbol):
    return {symbol: _d(weight) for symbol, weight in sorted(config.get("weights", {}).items())}

def sma_trend(config, series_by_symbol):
    fast, slow = int(config["fast_window"]), int(config["slow_window"])
    if fast >= slow: raise ValueError("fast_window must be less than slow_window")
    weight = _d(config["target_weight"])
    result = {}
    for symbol, bars in sorted(series_by_symbol.items()):
        closes = [_d(x["close"]) for x in bars]
        if len(closes) < slow: result[symbol] = D(0); continue
        fast_sma = sum(closes[-fast:]) / fast
        slow_sma = sum(closes[-slow:]) / slow
        result[symbol] = weight if fast_sma > slow_sma else D(0)
    return result

def rsi_mean_reversion(config, series_by_symbol):
    window = int(config["rsi_window"]); entry = _d(config["entry_threshold"]); exit_ = _d(config["exit_threshold"])
    weight = _d(config["target_weight"]); current = config.get("current_targets", {})
    result = {}
    for symbol, bars in sorted(series_by_symbol.items()):
        closes = [_d(x["close"]) for x in bars]
        if len(closes) <= window: result[symbol] = D(0); continue
        changes = [closes[i] - closes[i - 1] for i in range(len(closes) - window, len(closes))]
        avg_gain = sum(max(x, D(0)) for x in changes) / window
        avg_loss = sum(max(-x, D(0)) for x in changes) / window
        rsi = D(100) if avg_loss == 0 else D(100) - (D(100) / (D(1) + avg_gain / avg_loss))
        previous = _d(current.get(symbol, 0))
        result[symbol] = weight if rsi < entry else (D(0) if rsi > exit_ else previous)
    return result

def donchian_breakout(config, series_by_symbol):
    entry_w, exit_w = int(config["entry_window"]), int(config["exit_window"])
    weight = _d(config["target_weight"]); current = config.get("current_targets", {})
    result = {}
    for symbol, bars in sorted(series_by_symbol.items()):
        if len(bars) <= max(entry_w, exit_w): result[symbol] = D(0); continue
        price = _d(bars[-1]["close"])
        upper = max(_d(x["high"]) for x in bars[-entry_w-1:-1])
        lower = min(_d(x["low"]) for x in bars[-exit_w-1:-1])
        previous = _d(current.get(symbol, 0))
        result[symbol] = weight if price > upper else (D(0) if price < lower else previous)
    return result

def volatility_target_momentum(config, series_by_symbol):
    mw, vw = int(config["momentum_window"]), int(config["volatility_window"])
    target_vol, max_weight = _d(config["target_volatility"]), _d(config["maximum_weight"])
    result = {}
    for symbol, bars in sorted(series_by_symbol.items()):
        closes = [_d(x["close"]) for x in bars]
        if len(closes) <= max(mw, vw): result[symbol] = D(0); continue
        momentum = closes[-1] / closes[-mw-1] - D(1)
        returns = [closes[i] / closes[i-1] - D(1) for i in range(len(closes)-vw, len(closes))]
        mean = sum(returns) / len(returns)
        variance = sum((x - mean) ** 2 for x in returns) / max(1, len(returns)-1)
        annual_vol = _d(sqrt(float(variance * D(252))))
        scaled = D(0) if annual_vol == 0 or momentum == 0 else (D(1) if momentum > 0 else D(-1)) * target_vol / annual_vol
        result[symbol] = _cap(scaled, max_weight).quantize(D("0.00000001"))
    return result

STRATEGIES = {
    "fixed_weight": fixed_weight,
    "sma_trend": sma_trend,
    "rsi_mean_reversion": rsi_mean_reversion,
    "donchian_breakout": donchian_breakout,
    "volatility_target_momentum": volatility_target_momentum,
}

def calculate(strategy_type, configuration, series_by_symbol):
    try: fn = STRATEGIES[strategy_type]
    except KeyError as exc: raise ValueError(f"Unknown strategy: {strategy_type}") from exc
    return fn(configuration, series_by_symbol)

