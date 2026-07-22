from .settings import *  # noqa: F403,F401


DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}
APP_BASE_PATH = ""
FORCE_SCRIPT_NAME = None
PUBLIC_BASE_URL = ""
KAFKA_ENABLED = False
BROKER_SESSION_ENCRYPTION_KEY = "backend-test-encryption-key"
