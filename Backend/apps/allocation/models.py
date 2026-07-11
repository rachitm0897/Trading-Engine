from django.db import models

class RebalanceRun(models.Model):
    portfolio = models.ForeignKey("portfolios.TradingPortfolio", on_delete=models.PROTECT)
    trigger = models.CharField(max_length=40)
    idempotency_key = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=24, default="CALCULATING")
    created_at = models.DateTimeField(auto_now_add=True)

class TargetPortfolioPosition(models.Model):
    rebalance = models.ForeignKey(RebalanceRun, on_delete=models.PROTECT, related_name="targets")
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT)
    target_weight = models.DecimalField(max_digits=12, decimal_places=8)
    target_quantity = models.DecimalField(max_digits=24, decimal_places=8)
    trade_quantity = models.DecimalField(max_digits=24, decimal_places=8)
    reference_price = models.DecimalField(max_digits=24, decimal_places=8)

