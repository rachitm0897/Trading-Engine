from django.db import models

class ReconciliationRun(models.Model):
    trigger = models.CharField(max_length=40)
    status = models.CharField(max_length=24, default="RUNNING")
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

class ReconciliationBreak(models.Model):
    run = models.ForeignKey(ReconciliationRun, on_delete=models.PROTECT, related_name="breaks")
    category = models.CharField(max_length=32)
    severity = models.CharField(max_length=16)
    internal_value = models.JSONField(default=dict)
    broker_value = models.JSONField(default=dict)
    material = models.BooleanField(default=False)
    resolved = models.BooleanField(default=False)
    resolution = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

