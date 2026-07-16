import numpy as np

from ..engines.base import ResearchSignalResult, SingleAssetResearchStrategy
from ..services.features import momentum, realized_volatility, rsi, shifted_donchian, sma


def _columns(bars):
    return {
        key: np.asarray([float(item[key]) for item in bars], dtype=float)
        for key in ("open", "high", "low", "close")
    }


class BuyAndHoldResearch(SingleAssetResearchStrategy):
    def signals(self, bars, parameters, context):
        return ResearchSignalResult([1.0] * len(bars), {"warmup_bars": 0})


class FixedWeightResearch(SingleAssetResearchStrategy):
    def signals(self, bars, parameters, context):
        weight = float(parameters.get("target_weight", 1.0))
        if context.long_only and weight < 0:
            raise ValueError("Fixed-weight long-only adapter cannot short")
        return ResearchSignalResult([weight] * len(bars), {"warmup_bars": 0})


class SMACrossoverResearch(SingleAssetResearchStrategy):
    def signals(self, bars, parameters, context):
        close = _columns(bars)["close"]
        fast_window = int(parameters.get("fast_window", 20))
        slow_window = int(parameters.get("slow_window", 50))
        if fast_window >= slow_window:
            raise ValueError("fast_window must be less than slow_window")
        fast, slow = sma(close, fast_window), sma(close, slow_window)
        exposure = np.zeros(len(close))
        held = False
        for index in range(1, len(close)):
            if np.isnan(fast[index]) or np.isnan(slow[index]) or np.isnan(fast[index - 1]) or np.isnan(slow[index - 1]):
                continue
            if held and fast[index - 1] >= slow[index - 1] and fast[index] < slow[index]:
                held = False
            elif not held and fast[index - 1] <= slow[index - 1] and fast[index] > slow[index]:
                held = True
            exposure[index] = 1.0 if held else 0.0
        return ResearchSignalResult(exposure.tolist(), {"warmup_bars": slow_window, "fast": fast.tolist(), "slow": slow.tolist()})


class RSIMeanReversionResearch(SingleAssetResearchStrategy):
    def signals(self, bars, parameters, context):
        close = _columns(bars)["close"]
        window = int(parameters.get("window", 14))
        entry = float(parameters.get("entry_threshold", 30))
        exit_ = float(parameters.get("exit_threshold", 65))
        if entry >= exit_:
            raise ValueError("entry_threshold must be below exit_threshold")
        values = rsi(close, window)
        exposure = np.zeros(len(close))
        held = False
        for index in range(1, len(close)):
            previous, current = values[index - 1], values[index]
            if np.isnan(previous) or np.isnan(current):
                continue
            if held and previous <= exit_ < current:
                held = False
            elif not held and previous <= entry < current:
                held = True
            exposure[index] = 1.0 if held else 0.0
        return ResearchSignalResult(exposure.tolist(), {"warmup_bars": window + 1, "rsi": values.tolist()})


class DonchianBreakoutResearch(SingleAssetResearchStrategy):
    def signals(self, bars, parameters, context):
        columns = _columns(bars)
        entry_window = int(parameters.get("entry_window", 20))
        exit_window = int(parameters.get("exit_window", 10))
        entry_upper, _ = shifted_donchian(columns["high"], columns["low"], entry_window)
        _, exit_lower = shifted_donchian(columns["high"], columns["low"], exit_window)
        exposure = np.zeros(len(bars))
        held = False
        for index, close in enumerate(columns["close"]):
            if held and not np.isnan(exit_lower[index]) and close < exit_lower[index]:
                held = False
            elif not held and not np.isnan(entry_upper[index]) and close > entry_upper[index]:
                held = True
            exposure[index] = 1.0 if held else 0.0
        return ResearchSignalResult(exposure.tolist(), {"warmup_bars": max(entry_window, exit_window) + 1})


class VolatilityTargetMomentumResearch(SingleAssetResearchStrategy):
    def signals(self, bars, parameters, context):
        close = _columns(bars)["close"]
        momentum_window = int(parameters.get("momentum_window", 20))
        volatility_window = int(parameters.get("volatility_window", 20))
        target = float(parameters.get("target_volatility", 0.10))
        maximum = float(parameters.get("maximum_weight", 0.20))
        direction = parameters.get("direction", "LONG")
        signal = momentum(close, momentum_window)
        vol = realized_volatility(close, volatility_window)
        exposure = np.zeros(len(close))
        for index in range(len(close)):
            if np.isnan(signal[index]) or np.isnan(vol[index]) or vol[index] <= 0 or signal[index] == 0:
                continue
            weight = np.sign(signal[index]) * target / vol[index]
            weight = max(-maximum, min(maximum, weight))
            if context.long_only or direction == "LONG":
                weight = max(0.0, weight)
            exposure[index] = weight
        return ResearchSignalResult(exposure.tolist(), {"warmup_bars": max(momentum_window, volatility_window) + 1})


IMPLEMENTATIONS = {
    "BUY_AND_HOLD": BuyAndHoldResearch(),
    "FIXED_WEIGHT_REBALANCE": FixedWeightResearch(),
    "SMA_CROSSOVER": SMACrossoverResearch(),
    "RSI_MEAN_REVERSION": RSIMeanReversionResearch(),
    "DONCHIAN_BREAKOUT": DonchianBreakoutResearch(),
    "VOLATILITY_TARGET_MOMENTUM": VolatilityTargetMomentumResearch(),
}


def implementation_for(key):
    try:
        return IMPLEMENTATIONS[str(key).upper()]
    except KeyError as exc:
        raise ValueError(f"No exact research implementation registered for {key}") from exc
