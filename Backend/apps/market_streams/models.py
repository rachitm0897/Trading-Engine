from django.db import models


class MarketBar(models.Model):
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT, related_name="stream_bars")
    bar_id = models.CharField(max_length=160)
    interval = models.CharField(max_length=16)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    open = models.DecimalField(max_digits=24, decimal_places=8)
    high = models.DecimalField(max_digits=24, decimal_places=8)
    low = models.DecimalField(max_digits=24, decimal_places=8)
    close = models.DecimalField(max_digits=24, decimal_places=8)
    volume = models.DecimalField(max_digits=28, decimal_places=8, default=0)
    version = models.PositiveIntegerField(default=1)
    is_final = models.BooleanField(default=False)
    source_event_count = models.PositiveIntegerField(default=0)
    produced_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["bar_id", "version"], name="unique_market_bar_version")]


class IndicatorValue(models.Model):
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT, related_name="indicators")
    bar = models.ForeignKey(MarketBar, on_delete=models.PROTECT, null=True, blank=True)
    indicator = models.CharField(max_length=64)
    value = models.DecimalField(max_digits=28, decimal_places=10, null=True, blank=True)
    parameters = models.JSONField(default=dict)
    parameters_hash = models.CharField(max_length=64, blank=True)
    previous_value = models.DecimalField(max_digits=28, decimal_places=10, null=True, blank=True)
    timeframe = models.CharField(max_length=16, blank=True)
    source_bar_id = models.CharField(max_length=160, blank=True)
    source_bar_version = models.PositiveIntegerField(default=1)
    is_final = models.BooleanField(default=True)
    parameter_version = models.PositiveIntegerField(default=1)
    event_time = models.DateTimeField()
    source_key = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source_key", "parameter_version"], name="unique_indicator_source_version")]


class InstrumentMarketState(models.Model):
    STATES = [(x, x) for x in ["FRESH", "STALE", "UNAVAILABLE"]]
    instrument = models.OneToOneField("instruments.Instrument", on_delete=models.PROTECT, related_name="market_state")
    status = models.CharField(max_length=16, choices=STATES, default="UNAVAILABLE")
    reference_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    latest_event_at = models.DateTimeField(null=True, blank=True)
    watermark_at = models.DateTimeField(null=True, blank=True)
    stale_after_seconds = models.PositiveIntegerField(default=300)
    source_event_id = models.UUIDField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_usable(self, at=None):
        from django.utils import timezone
        at = at or timezone.now()
        if self.status != "FRESH" or not self.latest_event_at or self.reference_price is None:
            return False
        return (at - self.latest_event_at).total_seconds() <= self.stale_after_seconds
