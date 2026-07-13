from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TradingStrategy(models.Model):
    """Legacy allocation identity retained as a compatibility adapter."""

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


class StrategyDefinition(models.Model):
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    plugin_path = models.CharField(max_length=255)
    input_requirements = models.JSONField(default=list)
    parameter_schema = models.JSONField(default=dict)
    supported_asset_types = models.JSONField(default=list)
    supported_directions = models.JSONField(default=list)
    supported_timeframes = models.JSONField(default=list)
    version = models.PositiveIntegerField(default=1)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.key = self.key.upper()
        return super().save(*args, **kwargs)


class OrderPolicy(models.Model):
    name = models.CharField(max_length=128, unique=True)
    order_type = models.CharField(max_length=16, default="LMT")
    time_in_force = models.CharField(max_length=8, default="DAY")
    limit_offset_bps = models.DecimalField(max_digits=10, decimal_places=4, default=0)
    price_collar_bps = models.DecimalField(max_digits=10, decimal_places=4, default=50)
    allow_market_order = models.BooleanField(default=False)
    replace_after_seconds = models.PositiveIntegerField(default=60)
    maximum_replacements = models.PositiveIntegerField(default=2)
    cancel_at_session_end = models.BooleanField(default=True)
    outside_regular_hours = models.BooleanField(default=False)
    enabled = models.BooleanField(default=True)


class StrategyRiskPolicy(models.Model):
    name = models.CharField(max_length=128, unique=True)
    maximum_weight = models.DecimalField(max_digits=10, decimal_places=8, default="0.10")
    maximum_notional = models.DecimalField(max_digits=24, decimal_places=8, default="100000")
    maximum_quantity = models.DecimalField(max_digits=24, decimal_places=8, default="100000")
    allow_short = models.BooleanField(default=False)
    configuration = models.JSONField(default=dict)
    enabled = models.BooleanField(default=True)


class StrategyInstance(models.Model):
    MODES = [(x, x) for x in ["OBSERVE", "SHADOW", "PAPER"]]
    STATES = [(x, x) for x in ["FLAT", "ENTRY_PENDING", "PARTIALLY_LONG", "LONG", "EXIT_PENDING",
        "PARTIALLY_SHORT", "SHORT", "PAUSED", "BLOCKED", "WARMING_UP", "ERROR"]]
    name = models.CharField(max_length=128)
    definition = models.ForeignKey(StrategyDefinition, on_delete=models.PROTECT, related_name="instances")
    portfolio = models.ForeignKey("portfolios.TradingPortfolio", on_delete=models.PROTECT, related_name="strategy_instances")
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT, related_name="strategy_instances")
    universe = models.JSONField(default=list, blank=True)
    timeframe = models.CharField(max_length=16)
    parameters = models.JSONField(default=dict)
    target_configuration = models.JSONField(default=dict)
    risk_policy = models.ForeignKey(StrategyRiskPolicy, on_delete=models.PROTECT, null=True, blank=True)
    order_policy = models.ForeignKey(OrderPolicy, on_delete=models.PROTECT, null=True, blank=True)
    execution_mode = models.CharField(max_length=16, choices=MODES, default="SHADOW")
    state = models.CharField(max_length=24, choices=STATES, default="WARMING_UP")
    enabled = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    effective_from = models.DateTimeField(null=True, blank=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    legacy_strategy = models.OneToOneField(TradingStrategy, on_delete=models.PROTECT, related_name="strategy_instance", null=True, blank=True)
    state_data = models.JSONField(default=dict)
    warmup_progress = models.PositiveIntegerField(default=0)
    warmup_started_at = models.DateTimeField(null=True, blank=True)
    warmup_last_progress_at = models.DateTimeField(null=True, blank=True)
    block_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["portfolio", "name"], name="unique_strategy_instance_name")]

    def clean(self):
        if self.execution_mode == "LIVE":
            raise ValidationError("Live mode is unavailable for configurable strategies")


class StrategyVersion(models.Model):
    strategy_instance = models.ForeignKey(StrategyInstance, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    configuration_snapshot = models.JSONField(default=dict)
    parameter_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["strategy_instance", "version"], name="unique_strategy_version")]

    def save(self, *args, **kwargs):
        if self.pk and StrategyVersion.objects.filter(pk=self.pk).exists():
            raise ValidationError("StrategyVersion records are immutable")
        return super().save(*args, **kwargs)


class StrategyInputRequirement(models.Model):
    TYPES = [(x, x) for x in ["BAR", "INDICATOR"]]
    identity_hash = models.CharField(max_length=64, unique=True)
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT, related_name="strategy_input_requirements")
    timeframe = models.CharField(max_length=16)
    input_type = models.CharField(max_length=16, choices=TYPES)
    name = models.CharField(max_length=64)
    parameters = models.JSONField(default=dict)
    parameters_hash = models.CharField(max_length=64)
    required_bar_fields = models.JSONField(default=list)
    warmup_bars = models.PositiveIntegerField(default=0)
    active_ref_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)


class StrategyInputBinding(models.Model):
    strategy_instance = models.ForeignKey(StrategyInstance, on_delete=models.PROTECT, related_name="input_bindings")
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT, related_name="input_bindings")
    requirement = models.ForeignKey(StrategyInputRequirement, on_delete=models.PROTECT, related_name="bindings")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["strategy_version", "requirement"], name="unique_version_input_requirement")]


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
    strategy = models.ForeignKey(TradingStrategy, on_delete=models.PROTECT, related_name="runs", null=True, blank=True)
    strategy_instance = models.ForeignKey(StrategyInstance, on_delete=models.PROTECT, related_name="runs", null=True, blank=True)
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT, related_name="runs", null=True, blank=True)
    input_hash = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=255, null=True, blank=True, unique=True)
    triggering_event_id = models.CharField(max_length=160, blank=True)
    source_data_version = models.PositiveIntegerField(default=1)
    configuration_snapshot = models.JSONField(default=dict)
    context_snapshot = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default="RUNNING")
    error = models.TextField(blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["strategy", "input_hash"], name="unique_strategy_input")]


class StrategySignal(models.Model):
    run = models.OneToOneField(StrategyRun, on_delete=models.PROTECT, related_name="signal")
    strategy_instance = models.ForeignKey(StrategyInstance, on_delete=models.PROTECT, related_name="signals")
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT, related_name="signals")
    signal_type = models.CharField(max_length=32)
    signal_time = models.DateTimeField()
    reason = models.CharField(max_length=255, blank=True)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class StrategyTarget(models.Model):
    TARGET_TYPES = [(x, x) for x in ["WEIGHT", "VALUE", "QUANTITY", "FLAT"]]
    run = models.ForeignKey(StrategyRun, on_delete=models.PROTECT, related_name="targets")
    strategy_instance = models.ForeignKey(StrategyInstance, on_delete=models.PROTECT, related_name="targets", null=True, blank=True)
    strategy_version = models.ForeignKey(StrategyVersion, on_delete=models.PROTECT, related_name="targets", null=True, blank=True)
    portfolio = models.ForeignKey("portfolios.TradingPortfolio", on_delete=models.PROTECT, null=True, blank=True)
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT)
    target_type = models.CharField(max_length=16, choices=TARGET_TYPES, default="WEIGHT")
    target_weight = models.DecimalField(max_digits=12, decimal_places=8, default=0)
    target_value = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    target_quantity = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    direction = models.CharField(max_length=16, default="FLAT")
    signal_type = models.CharField(max_length=32, default="SET_TARGET")
    signal_time = models.DateTimeField(null=True, blank=True)
    source_event_id = models.CharField(max_length=160, blank=True)
    reason = models.CharField(max_length=255, blank=True)
    rationale = models.CharField(max_length=255, blank=True)
    confidence = models.DecimalField(max_digits=8, decimal_places=6, null=True, blank=True)
    status = models.CharField(max_length=24, default="ACTIVE")
    created_at = models.DateTimeField(default=timezone.now)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "instrument"], name="unique_run_target")]


class StrategyAttributedPosition(models.Model):
    strategy_instance = models.ForeignKey(StrategyInstance, on_delete=models.PROTECT, related_name="attributed_positions")
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT)
    portfolio = models.ForeignKey("portfolios.TradingPortfolio", on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    average_cost = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["strategy_instance", "instrument", "portfolio"], name="unique_strategy_attributed_position")]


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
