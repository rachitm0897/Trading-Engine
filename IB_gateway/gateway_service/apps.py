from django.apps import AppConfig
from django.db.backends.signals import connection_created

def sqlite_wal(sender, connection, **kwargs):
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")

class GatewayServiceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gateway_service"
    def ready(self): connection_created.connect(sqlite_wal, dispatch_uid="gateway_sqlite_wal")

