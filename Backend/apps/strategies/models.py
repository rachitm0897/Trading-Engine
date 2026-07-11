from django.db import models

class TradingStrategy(models.Model):
    TYPES = [(x, x) for x in ["fixed_weight", "sma_trend", "rsi_mean_reversion", "donchian_breakout", "volatility_target_momentum"]]
    name = models.CharField(max_length=128)
    strategy_type = models.CharField(max_length=40, choices=TYPES)
    version = models.PositiveIntegerField(default=1)
    enabled = models.BooleanField(default=True)
    schedule = models.CharField(max_length=64, default="manual")
    configuration = models.JSONField(default=dict)
    universe = models.ManyToManyField("instruments.Instrument", blank=True)
    allocated_capital = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    maximum_target_weight = models.DecimalField(max_digits=8, decimal_places=6, default=1)
    kill_switch = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class HistoricalBar(models.Model):
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT)
    timestamp = models.DateTimeField()
    open = models.DecimalField(max_digits=24, decimal_places=8)
    high = models.DecimalField(max_digits=24, decimal_places=8)
    low = models.DecimalField(max_digits=24, decimal_places=8)
    close = models.DecimalField(max_digits=24, decimal_places=8)
    volume = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["instrument", "timestamp"], name="unique_historical_bar")]

class StrategyRun(models.Model):
    strategy = models.ForeignKey(TradingStrategy, on_delete=models.PROTECT, related_name="runs")
    input_hash = models.CharField(max_length=64)
    configuration_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default="RUNNING")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["strategy", "input_hash"], name="unique_strategy_input")]

class StrategyTarget(models.Model):
    run = models.ForeignKey(StrategyRun, on_delete=models.PROTECT, related_name="targets")
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT)
    target_weight = models.DecimalField(max_digits=12, decimal_places=8)
    rationale = models.CharField(max_length=255, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "instrument"], name="unique_run_target")]

class StrategyAllocation(models.Model):
    strategy = models.ForeignKey(TradingStrategy, on_delete=models.PROTECT)
    portfolio = models.ForeignKey("portfolios.TradingPortfolio", on_delete=models.PROTECT)
    weight = models.DecimalField(max_digits=12, decimal_places=8)
    minimum_share = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    maximum_share = models.DecimalField(max_digits=12, decimal_places=8, default=1)
    capacity = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    minimum_allocation = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    priority = models.PositiveIntegerField(default=100)
    idle_cash = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["strategy", "portfolio"], name="unique_strategy_allocation")]
