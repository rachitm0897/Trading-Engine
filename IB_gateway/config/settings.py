import os
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "gateway-test-secret")
DEBUG = False
ALLOWED_HOSTS = ["*"]
APP_BASE_PATH = "/" + os.getenv("APP_BASE_PATH", "").strip("/") if os.getenv("APP_BASE_PATH", "").strip("/") else ""
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
INSTALLED_APPS = ["django.contrib.contenttypes", "gateway_service"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "config.urls"
TEMPLATES = []
WSGI_APPLICATION = "config.wsgi.application"
DATABASES = {"default":{"ENGINE":"django.db.backends.sqlite3", "NAME":os.getenv("GATEWAY_DB_PATH", str(BASE_DIR / "gateway.sqlite3")), "OPTIONS":{"timeout":20}}}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
GATEWAY_SERVICE_TOKEN = os.getenv("GATEWAY_SERVICE_TOKEN", "test-token")
if os.getenv("IBC_TRADING_MODE", "paper").lower() != "paper":
    raise RuntimeError("Live trading is disabled; the Gateway supports paper trading only")
IBC_TRADING_MODE = "paper"
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "17"))
BROKER_ADAPTER = os.getenv("BROKER_ADAPTER", "mock")
TWS_PORT = 4002
BROKER_REFRESH_SECONDS = max(2, int(os.getenv("BROKER_REFRESH_SECONDS", "5")))
GATEWAY_EVENT_RETENTION_DAYS = int(os.getenv("GATEWAY_EVENT_RETENTION_DAYS", "7"))
GATEWAY_HEALTH_RETENTION_DAYS = int(os.getenv("GATEWAY_HEALTH_RETENTION_DAYS", "7"))
GATEWAY_COMPACTION_SECONDS = max(300, int(os.getenv("GATEWAY_COMPACTION_SECONDS", "3600")))
GATEWAY_COMPACTION_BATCH_SIZE = int(os.getenv("GATEWAY_COMPACTION_BATCH_SIZE", "1000"))
