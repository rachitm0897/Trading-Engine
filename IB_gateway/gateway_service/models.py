from django.db import models

class GatewaySession(models.Model):
    state = models.CharField(max_length=32, default="DISCONNECTED")
    mode = models.CharField(max_length=8, default="paper")
    reconciled = models.BooleanField(default=False)
    connection_owner = models.CharField(max_length=128, blank=True)
    last_callback_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

class GatewayCommand(models.Model):
    TYPES = [(x,x) for x in ["RECONNECT","QUALIFY","PLACE_ORDER","MODIFY_ORDER","CANCEL_ORDER","KILL_SWITCH","REFRESH"]]
    command_type = models.CharField(max_length=32, choices=TYPES)
    idempotency_key = models.CharField(max_length=128, unique=True)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=24, default="PENDING")
    result = models.JSONField(default=dict)
    error = models.CharField(max_length=1000, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class GatewayEvent(models.Model):
    event_key = models.CharField(max_length=160, unique=True)
    event_type = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)
    acknowledged = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class GatewayOrderReference(models.Model):
    internal_id = models.CharField(max_length=64, unique=True)
    broker_order_id = models.CharField(max_length=64, blank=True)
    permanent_id = models.CharField(max_length=64, blank=True)
    last_status = models.CharField(max_length=32, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

class GatewayHealthSnapshot(models.Model):
    connected = models.BooleanField(default=False)
    reconciled = models.BooleanField(default=False)
    broker_time = models.DateTimeField(null=True, blank=True)
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

