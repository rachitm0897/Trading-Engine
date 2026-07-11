from django.db import models

class Fill(models.Model):
    order = models.ForeignKey("oms.Order", on_delete=models.PROTECT, related_name="fills")
    execution_id = models.CharField(max_length=128, unique=True)
    quantity = models.DecimalField(max_digits=24, decimal_places=8)
    price = models.DecimalField(max_digits=24, decimal_places=8)
    commission = models.DecimalField(max_digits=24, decimal_places=8, default=0)
    currency = models.CharField(max_length=8, default="USD")
    executed_at = models.DateTimeField()
    raw_event = models.JSONField(default=dict)

