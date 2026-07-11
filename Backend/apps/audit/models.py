from django.db import models

class AuditEvent(models.Model):
    event_type = models.CharField(max_length=64)
    actor = models.CharField(max_length=128)
    aggregate_type = models.CharField(max_length=64)
    aggregate_id = models.CharField(max_length=128)
    data = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

class OutboxEvent(models.Model):
    topic = models.CharField(max_length=128)
    aggregate_id = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128, unique=True)
    published_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

