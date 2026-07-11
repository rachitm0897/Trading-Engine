from django.db import models

class BrokerSyncCursor(models.Model):
    name = models.CharField(max_length=64, unique=True, default="gateway-events")
    last_sequence = models.BigIntegerField(default=0)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=1000, blank=True)

