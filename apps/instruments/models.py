from django.db import models

class Instrument(models.Model):
    symbol = models.CharField(max_length=32)
    asset_class = models.CharField(max_length=24, default="STK")
    exchange = models.CharField(max_length=32, default="SMART")
    currency = models.CharField(max_length=8, default="USD")
    sector = models.CharField(max_length=64, blank=True)
    lot_size = models.DecimalField(max_digits=20, decimal_places=8, default=1)
    min_tick = models.DecimalField(max_digits=20, decimal_places=8, default="0.01")
    tradable = models.BooleanField(default=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["symbol", "asset_class", "exchange", "currency"], name="unique_instrument")]

class BrokerContract(models.Model):
    instrument = models.OneToOneField(Instrument, on_delete=models.PROTECT, related_name="broker_contract")
    conid = models.BigIntegerField(unique=True)
    primary_exchange = models.CharField(max_length=32, blank=True)
    local_symbol = models.CharField(max_length=64, blank=True)
    qualified_at = models.DateTimeField(null=True, blank=True)

