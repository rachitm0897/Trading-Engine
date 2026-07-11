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
IBC_TRADING_MODE = os.getenv("IBC_TRADING_MODE", "paper").lower()
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "17"))
BROKER_ADAPTER = os.getenv("BROKER_ADAPTER", "mock")
TWS_PORT = 4001 if IBC_TRADING_MODE == "live" else 4002
BROKER_REFRESH_SECONDS = max(2, int(os.getenv("BROKER_REFRESH_SECONDS", "5")))
