from django.db import models

ORDER_STATES = [x for x in "CREATED RISK_APPROVED QUEUED BROKER_BLOCKED SUBMITTED ACKNOWLEDGED PARTIALLY_FILLED FILLED CANCEL_PENDING CANCELLED REJECTED EXPIRED UNKNOWN".split()]

class OrderIntent(models.Model):
    rebalance = models.ForeignKey("allocation.RebalanceRun", on_delete=models.PROTECT, null=True, blank=True)
    portfolio = models.ForeignKey("portfolios.TradingPortfolio", on_delete=models.PROTECT)
    strategy = models.ForeignKey("strategies.TradingStrategy", on_delete=models.PROTECT, null=True, blank=True)
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.PROTECT)
    side = models.CharField(max_length=4)
    quantity = models.DecimalField(max_digits=24, decimal_places=8)
    order_type = models.CharField(max_length=16, default="MKT")
    limit_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    stop_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    reference_price = models.DecimalField(max_digits=24, decimal_places=8, null=True, blank=True)
    time_in_force = models.CharField(max_length=8, default="DAY")
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Order(models.Model):
    intent = models.OneToOneField(OrderIntent, on_delete=models.PROTECT, related_name="order")
    internal_id = models.CharField(max_length=64, unique=True)
    broker_order_id = models.CharField(max_length=64, blank=True)
    broker_permanent_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=24, choices=[(x, x) for x in ORDER_STATES], default="CREATED")
    quantity = models.DecimalField(max_digits=24, decimal_places=8)
    filled_quantity = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    average_fill_price = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="status_history")
    from_status = models.CharField(max_length=24, blank=True)
    to_status = models.CharField(max_length=24)
    source = models.CharField(max_length=32)
    reason = models.CharField(max_length=255, blank=True)
    event_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
