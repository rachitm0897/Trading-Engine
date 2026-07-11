import uuid
from django.db import models
from django.utils import timezone

class AuditEvent(models.Model):
    event_type = models.CharField(max_length=64)
    actor = models.CharField(max_length=128)
    aggregate_type = models.CharField(max_length=64)
    aggregate_id = models.CharField(max_length=128)
    data = models.JSONField(default=dict)
    idempotency_key = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

class OutboxEvent(models.Model):
    STATUSES = [(x, x) for x in ["PENDING", "PUBLISHING", "PUBLISHED", "FAILED"]]
    event_id = models.UUIDField(unique=True, editable=False, default=uuid.uuid4)
    topic = models.CharField(max_length=128)
    partition_key = models.CharField(max_length=128, default="")
    event_type = models.CharField(max_length=128, default="")
    schema_version = models.PositiveIntegerField(default=1)
    aggregate_type = models.CharField(max_length=64, default="system")
    aggregate_id = models.CharField(max_length=128)
    payload = models.JSONField(default=dict)
    correlation_id = models.UUIDField(null=True, blank=True)
    causation_id = models.UUIDField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, choices=STATUSES, default="PENDING")
    attempt_count = models.PositiveIntegerField(default=0)
    available_at = models.DateTimeField(default=timezone.now)
    published_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        import uuid
        from django.utils import timezone
        if not self.event_id:
            self.event_id = uuid.uuid4()
        if not self.partition_key:
            self.partition_key = str(self.aggregate_id)
        if not self.event_type:
            self.event_type = self.topic
        if not self.available_at:
            self.available_at = timezone.now()
        super().save(*args, **kwargs)

    @property
    def attempts(self):
        return self.attempt_count
