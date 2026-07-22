import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
from gateway_service.modes import normalize_trading_mode, tws_port_for_mode
from runtime_config import normalize_app_base_path, normalize_broker_adapter

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def required_environment(name):
    value = os.getenv(name, "")
    if not value.strip():
        raise ImproperlyConfigured(f"{name} is required")
    return value


SECRET_KEY = required_environment("DJANGO_SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = ["*"]
APP_BASE_PATH = normalize_app_base_path(os.getenv("APP_BASE_PATH", ""))
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
GATEWAY_SERVICE_TOKEN = required_environment("GATEWAY_SERVICE_TOKEN")
IBC_TRADING_MODE = normalize_trading_mode(os.getenv("IBC_TRADING_MODE", "paper"))
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "17"))
BROKER_ADAPTER = normalize_broker_adapter(os.getenv("BROKER_ADAPTER", "ib_async"))
TWS_PORT = tws_port_for_mode(IBC_TRADING_MODE)
BROKER_REFRESH_SECONDS = max(2, int(os.getenv("BROKER_REFRESH_SECONDS", "5")))
GATEWAY_EVENT_RETENTION_DAYS = int(os.getenv("GATEWAY_EVENT_RETENTION_DAYS", "7"))
GATEWAY_HEALTH_RETENTION_DAYS = int(os.getenv("GATEWAY_HEALTH_RETENTION_DAYS", "7"))
GATEWAY_COMPACTION_SECONDS = max(300, int(os.getenv("GATEWAY_COMPACTION_SECONDS", "3600")))
GATEWAY_COMPACTION_BATCH_SIZE = int(os.getenv("GATEWAY_COMPACTION_BATCH_SIZE", "1000"))
