from decimal import Decimal
import pytest
from apps.strategies.engine import calculate

def bars(values): return [{"open": x, "high": x, "low": x, "close": x, "volume": 1} for x in values]

def test_exactly_five_strategies_are_exposed():
    from apps.strategies.engine import STRATEGIES
    assert set(STRATEGIES) == {"fixed_weight", "sma_trend", "rsi_mean_reversion", "donchian_breakout", "volatility_target_momentum"}

def test_fixed_weight_is_sorted_and_decimal():
    result = calculate("fixed_weight", {"weights":{"MSFT":"0.4", "AAPL":"0.6"}}, {})
    assert list(result) == ["AAPL", "MSFT"] and result["AAPL"] == Decimal("0.6")

def test_sma_trend_long_and_flat():
    cfg = {"fast_window":2, "slow_window":3, "target_weight":"0.5"}
    assert calculate("sma_trend", cfg, {"UP":bars([1,2,3]), "DOWN":bars([3,2,1])}) == {"DOWN":Decimal(0), "UP":Decimal("0.5")}

def test_rsi_mean_reversion_entry():
    cfg = {"rsi_window":3, "entry_threshold":30, "exit_threshold":70, "target_weight":"0.4"}
    assert calculate("rsi_mean_reversion", cfg, {"X":bars([4,3,2,1])})["X"] == Decimal("0.4")

def test_donchian_breakout_entry():
    cfg = {"entry_window":3, "exit_window":2, "target_weight":"0.7"}
    assert calculate("donchian_breakout", cfg, {"X":bars([1,2,3,4])})["X"] == Decimal("0.7")

def test_volatility_target_momentum_is_capped():
    cfg = {"momentum_window":3, "volatility_window":3, "target_volatility":"0.2", "maximum_weight":"0.5"}
    value = calculate("volatility_target_momentum", cfg, {"X":bars([100,101,102,103])})["X"]
    assert Decimal(0) < value <= Decimal("0.5")

