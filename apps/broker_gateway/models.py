from django.db import models

class BrokerSyncCursor(models.Model):
    name = models.CharField(max_length=64, unique=True, default="gateway-events")
    last_sequence = models.BigIntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=1000, blank=True)


class BrokerPositionSnapshot(models.Model):
    broker_account = models.ForeignKey(
        "accounts.BrokerAccount",
        on_delete=models.PROTECT,
        related_name="position_snapshots",
    )
    snapshot_key = models.CharField(max_length=160, unique=True)
    complete = models.BooleanField(default=False)
    status = models.CharField(max_length=24, default="RECEIVED")
    row_count = models.PositiveIntegerField(default=0)
    positions = models.JSONField(default=list)
    attempt_count = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=1000, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["broker_account", "-received_at"], name="broker_pos_acct_received_idx"),
            models.Index(fields=["status", "received_at"], name="broker_pos_status_idx"),
        ]
