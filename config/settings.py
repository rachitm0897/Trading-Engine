import os
from pathlib import Path
import dj_database_url
from corsheaders.defaults import default_headers

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "test-only-secret")
DEBUG = os.getenv("DJANGO_DEBUG", "false").lower() == "true"
ALLOWED_HOSTS = [x.strip() for x in os.getenv("ALLOWED_HOSTS", "*").split(",") if x.strip()]
APP_BASE_PATH = "/" + os.getenv("APP_BASE_PATH", "").strip("/") if os.getenv("APP_BASE_PATH", "").strip("/") else ""
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
FORCE_SCRIPT_NAME = APP_BASE_PATH or None

INSTALLED_APPS = [
    "django.contrib.contenttypes", "django.contrib.auth", "django.contrib.sessions",
    "corsheaders", "rest_framework",
    "apps.core", "apps.instruments", "apps.broker_gateway", "apps.accounts",
    "apps.portfolios", "apps.strategies", "apps.allocation", "apps.risk",
    "apps.oms", "apps.execution", "apps.reconciliation", "apps.audit",
    "apps.event_bus", "apps.market_streams", "apps.rebalancing", "apps.position_sizing",
    "apps.market_data", "apps.portfolio_optimization", "apps.portfolio_construction",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = []
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": dj_database_url.config(default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60)}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
CORS_ALLOWED_ORIGINS = [x.strip() for x in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if x.strip()]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key")
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()]
REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": [], "DEFAULT_PERMISSION_CLASSES": []}
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/1")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/2")
CELERY_BEAT_SCHEDULE = {
    "reconcile": {"task": "apps.reconciliation.tasks.run_scheduled_reconciliation", "schedule": 60.0},
    "sync-broker": {"task": "apps.broker_gateway.tasks.sync_broker_events", "schedule": 5.0},
    "publish-outbox": {"task": "apps.event_bus.tasks.publish_outbox_events", "schedule": 2.0},
    "stream-health": {"task": "apps.event_bus.tasks.check_stream_health", "schedule": 30.0},
    "restore-market-subscriptions": {"task": "apps.market_streams.tasks.restore_active_market_subscriptions", "schedule": 15.0},
    "warmup-timeouts": {"task": "apps.market_streams.tasks.check_warmup_timeouts", "schedule": 30.0},
    "instrument-registry": {"task": "apps.instruments.tasks.publish_instrument_registry_snapshot", "schedule": 60.0},
    "recover-rebalances": {"task": "apps.rebalancing.tasks.recover_incomplete_rebalances", "schedule": 60.0},
    "sync-finnhub-history": {"task": "apps.market_data.tasks.sync_active_finnhub_universes", "schedule": 21600.0},
    "check-finnhub-history": {"task": "apps.market_data.tasks.check_finnhub_history_staleness", "schedule": 21600.0},
    "verify-finnhub-mappings": {"task": "apps.market_data.tasks.verify_pending_finnhub_mappings", "schedule": 21600.0},
    "monitor-market-data-providers": {"task": "apps.market_streams.tasks.monitor_market_data_providers", "schedule": 5.0},
    "compact-operational-records": {"task": "apps.event_bus.tasks.compact_operational_records", "schedule": 86400.0},
}
IB_GATEWAY_SERVICE_URL = os.getenv("IB_GATEWAY_SERVICE_URL", "http://localhost:8080/api/v1")
GATEWAY_SERVICE_TOKEN = os.getenv("GATEWAY_SERVICE_TOKEN", "test-token")
if os.getenv("ALLOW_LIVE_TRADING", "false").lower() == "true":
    raise RuntimeError("Live trading is disabled; this application supports paper trading only")
GLOBAL_KILL_SWITCH = os.getenv("GLOBAL_KILL_SWITCH", "false").lower() == "true"
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_CLIENT_ID = os.getenv("KAFKA_CLIENT_ID", "finflock-backend")
KAFKA_ENABLED = os.getenv("KAFKA_ENABLED", "false").lower() == "true"
NEW_EXECUTION_MODE = os.getenv("NEW_EXECUTION_MODE", "SHADOW").upper()
if NEW_EXECUTION_MODE not in {"SHADOW", "PAPER"}:
    raise RuntimeError("NEW_EXECUTION_MODE must be SHADOW or PAPER")
MARKET_PRICE_STALE_SECONDS = int(os.getenv("MARKET_PRICE_STALE_SECONDS", "300"))
WARMUP_SAFETY_BARS = int(os.getenv("WARMUP_SAFETY_BARS", "5"))
WARMUP_TIMEOUT_SECONDS = int(os.getenv("WARMUP_TIMEOUT_SECONDS", "300"))
MARKET_CONSUMER_HEARTBEAT_STALE_SECONDS = int(os.getenv("MARKET_CONSUMER_HEARTBEAT_STALE_SECONDS", "30"))
KAFKA_LAG_DEGRADED_THRESHOLD = int(os.getenv("KAFKA_LAG_DEGRADED_THRESHOLD", "1000"))
FLINK_REST_URL = os.getenv("FLINK_REST_URL", "http://localhost:8081")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
FINNHUB_BASE_URL = os.getenv("FINNHUB_BASE_URL", "https://finnhub.io/api/v1").rstrip("/")
FINNHUB_API_KEY_OVERRIDE_ENABLED = os.getenv("FINNHUB_API_KEY_OVERRIDE_ENABLED", "false").lower() == "true"
FINNHUB_REQUEST_TIMEOUT_SECONDS = int(os.getenv("FINNHUB_REQUEST_TIMEOUT_SECONDS", "15"))
FINNHUB_MAX_RETRIES = int(os.getenv("FINNHUB_MAX_RETRIES", "2"))
FINNHUB_ENCRYPTION_KEY = os.getenv("FINNHUB_ENCRYPTION_KEY", "")
FINNHUB_OPERATION_THROTTLE_LIMIT = int(os.getenv("FINNHUB_OPERATION_THROTTLE_LIMIT", "30"))
MARKET_DATA_FALLBACK_ENABLED = os.getenv("MARKET_DATA_FALLBACK_ENABLED", "false").lower() == "true"
FINNHUB_HISTORICAL_FALLBACK_ENABLED = os.getenv("FINNHUB_HISTORICAL_FALLBACK_ENABLED", "false").lower() == "true"
FINNHUB_LIVE_FALLBACK_ENABLED = os.getenv("FINNHUB_LIVE_FALLBACK_ENABLED", "false").lower() == "true"
FINNHUB_AUTO_FAILBACK_ENABLED = os.getenv("FINNHUB_AUTO_FAILBACK_ENABLED", "false").lower() == "true"
IBKR_MARKET_DATA_FAILOVER_GRACE_SECONDS = int(os.getenv("IBKR_MARKET_DATA_FAILOVER_GRACE_SECONDS", "15"))
FINNHUB_LIVE_STALE_SECONDS = int(os.getenv("FINNHUB_LIVE_STALE_SECONDS", "15"))
FINNHUB_WS_URL = os.getenv("FINNHUB_WS_URL", "wss://ws.finnhub.io").rstrip("/")
FINNHUB_WS_RECONNECT_MAX_SECONDS = int(os.getenv("FINNHUB_WS_RECONNECT_MAX_SECONDS", "30"))
FINNHUB_ALLOWED_LATENESS_SECONDS = int(os.getenv("FINNHUB_ALLOWED_LATENESS_SECONDS", "2"))
FINNHUB_WS_RECONCILE_SECONDS = int(os.getenv("FINNHUB_WS_RECONCILE_SECONDS", "2"))
PRIMARY_RECOVERY_CONFIRMATION_EVENTS = int(os.getenv("PRIMARY_RECOVERY_CONFIRMATION_EVENTS", "3"))
PRIMARY_PROBE_RETRY_SECONDS = int(os.getenv("PRIMARY_PROBE_RETRY_SECONDS", "30"))
FINNHUB_MAPPING_REVALIDATE_SECONDS = int(os.getenv("FINNHUB_MAPPING_REVALIDATE_SECONDS", "86400"))
FINNHUB_SUPPORTED_ASSET_CLASSES = tuple(
    value.strip().upper() for value in os.getenv("FINNHUB_SUPPORTED_ASSET_CLASSES", "STK").split(",") if value.strip()
)
OPTIMIZATION_THROTTLE_LIMIT = int(os.getenv("OPTIMIZATION_THROTTLE_LIMIT", "30"))
EXPENSIVE_OPERATION_THROTTLE_WINDOW_SECONDS = int(os.getenv("EXPENSIVE_OPERATION_THROTTLE_WINDOW_SECONDS", "60"))
OUTBOX_RETENTION_DAYS = int(os.getenv("OUTBOX_RETENTION_DAYS", "30"))
BROKER_SNAPSHOT_RETENTION_DAYS = int(os.getenv("BROKER_SNAPSHOT_RETENTION_DAYS", "30"))
READINESS_RETENTION_DAYS = int(os.getenv("READINESS_RETENTION_DAYS", "30"))
STREAM_HEALTH_RETENTION_DAYS = int(os.getenv("STREAM_HEALTH_RETENTION_DAYS", "30"))
OPERATIONAL_COMPACTION_BATCH_SIZE = int(os.getenv("OPERATIONAL_COMPACTION_BATCH_SIZE", "1000"))
