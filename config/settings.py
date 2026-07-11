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
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = []
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default": dj_database_url.config(default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=60)}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
CORS_ALLOWED_ORIGINS = [x.strip() for x in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if x.strip()]
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
    "recover-rebalances": {"task": "apps.rebalancing.tasks.recover_incomplete_rebalances", "schedule": 60.0},
}
IB_GATEWAY_SERVICE_URL = os.getenv("IB_GATEWAY_SERVICE_URL", "http://localhost:8080/api/v1")
GATEWAY_SERVICE_TOKEN = os.getenv("GATEWAY_SERVICE_TOKEN", "test-token")
ALLOW_LIVE_TRADING = os.getenv("ALLOW_LIVE_TRADING", "false").lower() == "true"
GLOBAL_KILL_SWITCH = os.getenv("GLOBAL_KILL_SWITCH", "false").lower() == "true"
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_CLIENT_ID = os.getenv("KAFKA_CLIENT_ID", "finflock-backend")
KAFKA_ENABLED = os.getenv("KAFKA_ENABLED", "false").lower() == "true"
NEW_EXECUTION_MODE = os.getenv("NEW_EXECUTION_MODE", "SHADOW").upper()
if NEW_EXECUTION_MODE not in {"SHADOW", "PAPER"}:
    raise RuntimeError("NEW_EXECUTION_MODE must be SHADOW or PAPER")
MARKET_PRICE_STALE_SECONDS = int(os.getenv("MARKET_PRICE_STALE_SECONDS", "300"))
FLINK_REST_URL = os.getenv("FLINK_REST_URL", "http://localhost:8081")
