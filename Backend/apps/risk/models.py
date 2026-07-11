from django.db import models

class KillSwitch(models.Model):
    scope = models.CharField(max_length=32)
    scope_id = models.CharField(max_length=64, blank=True)
    enabled = models.BooleanField(default=False)
    reason = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["scope", "scope_id"], name="unique_kill_switch")]

class RiskCheckResult(models.Model):
    DECISIONS = [(x, x) for x in ["APPROVED", "RESIZED", "HELD", "REJECTED"]]
    order_intent = models.ForeignKey("oms.OrderIntent", on_delete=models.PROTECT, related_name="risk_checks")
    check_name = models.CharField(max_length=64)
    decision = models.CharField(max_length=16, choices=DECISIONS)
    reason = models.CharField(max_length=255)
    requested_quantity = models.DecimalField(max_digits=24, decimal_places=8)
    approved_quantity = models.DecimalField(max_digits=24, decimal_places=8)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

