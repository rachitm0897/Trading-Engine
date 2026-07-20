import os
import sys
from pathlib import Path
import dj_database_url
from corsheaders.defaults import default_headers

from apps.research.configuration import RecommendationSystemConfiguration

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
    "apps.research",
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
ASGI_APPLICATION = "config.asgi.application"
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'db.sqlite3'}")
DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=60)}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
CORS_ALLOWED_ORIGINS = [x.strip() for x in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if x.strip()]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = (*default_headers, "idempotency-key")
CSRF_TRUSTED_ORIGINS = [x.strip() for x in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if x.strip()]
REST_FRAMEWORK = {"DEFAULT_AUTHENTICATION_CLASSES": [], "DEFAULT_PERMISSION_CLASSES": []}
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
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
    "research-universe-mapping": {"task": "apps.research.tasks.refresh_universe_mapping", "schedule": 86400.0},
    "research-daily-refresh": {"task": "apps.research.tasks.refresh_research_pipeline", "schedule": 86400.0},
    "research-intraday-refresh": {"task": "apps.research.tasks.refresh_intraday_data", "schedule": 3600.0},
    "research-fundamentals": {"task": "apps.research.tasks.refresh_fundamentals", "schedule": 86400.0},
    "research-events": {"task": "apps.research.tasks.refresh_events", "schedule": 3600.0},
    "research-features": {"task": "apps.research.tasks.calculate_features", "schedule": 86400.0},
    "research-experiments": {"task": "apps.research.tasks.schedule_research_experiments", "schedule": 86400.0},
    "research-experiment-dispatch": {"task": "apps.research.tasks.dispatch_research_experiments", "schedule": 60.0},
    "research-scoring": {"task": "apps.research.tasks.score_current_candidates", "schedule": 86400.0},
    "recommendation-cache": {"task": "apps.research.tasks.warm_recommendation_cache", "schedule": 86400.0},
}
ALLOW_LIVE_TRADING = os.getenv("ALLOW_LIVE_TRADING", "false").lower() == "true"
BROKER_SESSION_ENCRYPTION_KEY = os.getenv("BROKER_SESSION_ENCRYPTION_KEY", "")
BROKER_CREDENTIAL_TTL_SECONDS = int(os.getenv("BROKER_CREDENTIAL_TTL_SECONDS", "900"))
BROKER_SESSION_CREATING_STALE_SECONDS = int(os.getenv("BROKER_SESSION_CREATING_STALE_SECONDS", "60"))
BROKER_SESSION_START_TIMEOUT_SECONDS = float(os.getenv("BROKER_SESSION_START_TIMEOUT_SECONDS", "45"))
BROKER_SESSION_HEALTH_TIMEOUT_SECONDS = float(os.getenv("BROKER_SESSION_HEALTH_TIMEOUT_SECONDS", "5"))
NOVNC_ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("NOVNC_ACCESS_TOKEN_TTL_SECONDS", "300"))
NOVNC_PROXY_CONNECT_TIMEOUT_SECONDS = float(os.getenv("NOVNC_PROXY_CONNECT_TIMEOUT_SECONDS", "10"))
NOVNC_PROXY_IDLE_TIMEOUT_SECONDS = float(os.getenv("NOVNC_PROXY_IDLE_TIMEOUT_SECONDS", "300"))
NOVNC_PROXY_MAX_BODY_BYTES = int(os.getenv("NOVNC_PROXY_MAX_BODY_BYTES", str(10 * 1024 * 1024)))
QCH_APP_ID = os.getenv("QCH_APP_ID", "")
QCH_API_HOST = os.getenv("QCH_API_HOST", "").rstrip("/")
QCH_SERVICE_TOKEN = os.getenv("QCH_SERVICE_TOKEN", "")
QCH_REQUEST_TIMEOUT_SECONDS = float(os.getenv("QCH_REQUEST_TIMEOUT_SECONDS", "10"))
QCH_SUBCONTAINER_NETWORK = os.getenv("QCH_SUBCONTAINER_NETWORK", "traefik")
IBKR_GATEWAY_IMAGE = os.getenv("IBKR_GATEWAY_IMAGE", "")
BROKER_STATIC_DEVELOPMENT_GATEWAY_ENABLED = os.getenv(
    "BROKER_STATIC_DEVELOPMENT_GATEWAY_ENABLED",
    "true" if any("pytest" in value.lower() for value in sys.argv) else "false",
).lower() == "true"
STATIC_DEVELOPMENT_IB_GATEWAY_URL = os.getenv("STATIC_DEVELOPMENT_IB_GATEWAY_URL", "http://localhost:8080/api/v1")
STATIC_DEVELOPMENT_GATEWAY_SERVICE_TOKEN = os.getenv("STATIC_DEVELOPMENT_GATEWAY_SERVICE_TOKEN", "test-token")
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
RECOMMENDATION_CONFIG = RecommendationSystemConfiguration.from_environment(
    os.environ,
    default_artifact_root=BASE_DIR / "research_artifacts",
)
RESEARCH_ENABLED = RECOMMENDATION_CONFIG.research_enabled
RECOMMENDATION_SYSTEM_ENABLED = RECOMMENDATION_CONFIG.recommendation_system_enabled
RECOMMENDATION_UNIVERSE_KEY = RECOMMENDATION_CONFIG.universe_key
RECOMMENDATION_MAX_STOCKS = RECOMMENDATION_CONFIG.maximum_stocks
RECOMMENDATION_MIN_STOCKS = RECOMMENDATION_CONFIG.minimum_stocks
RECOMMENDATION_CANDIDATE_POOL_SIZE = RECOMMENDATION_CONFIG.candidate_pool_size
RECOMMENDATION_MAX_STRATEGIES_PER_STOCK = RECOMMENDATION_CONFIG.maximum_strategies_per_stock
RESEARCH_DAILY_LOOKBACK_YEARS = RECOMMENDATION_CONFIG.daily_lookback_years
RESEARCH_INTRADAY_LOOKBACK_DAYS = RECOMMENDATION_CONFIG.intraday_lookback_days
RESEARCH_MINIMUM_DAILY_BARS = RECOMMENDATION_CONFIG.minimum_daily_bars
RESEARCH_SCORE_MAX_AGE_DAYS = RECOMMENDATION_CONFIG.score_max_age_days
RESEARCH_STALE_SCORE_FALLBACK_DAYS = RECOMMENDATION_CONFIG.stale_score_fallback_days
RECOMMENDATION_SNAPSHOT_MAX_AGE_HOURS = RECOMMENDATION_CONFIG.snapshot_max_age_hours
RESEARCH_MAX_PARALLEL_DATA_TASKS = RECOMMENDATION_CONFIG.maximum_parallel_data_tasks
RESEARCH_MAX_PARALLEL_BACKTEST_TASKS = RECOMMENDATION_CONFIG.maximum_parallel_backtest_tasks
RESEARCH_BUNDLE_PATH = os.getenv(
    "RESEARCH_BUNDLE_PATH", str(BASE_DIR / "research_bundle")
)
RESEARCH_ARTIFACT_ROOT = str(RECOMMENDATION_CONFIG.artifact_root)
RESEARCH_DAILY_PROVIDER = os.getenv("RESEARCH_DAILY_PROVIDER", "FINNHUB").upper()
RESEARCH_RECOMMENDATION_MAX_AGE_DAYS = max(1, RECOMMENDATION_SNAPSHOT_MAX_AGE_HOURS // 24)
RESEARCH_TASK_ROUTES = {
    "apps.research.tasks.refresh_universe_mapping": {"queue": "research_mapping"},
    "apps.research.tasks.refresh_research_pipeline": {"queue": "research_daily_data"},
    "apps.research.tasks.refresh_intraday_data": {"queue": "research_intraday_data"},
    "apps.research.tasks.refresh_fundamentals": {"queue": "research_fundamentals"},
    "apps.research.tasks.refresh_events": {"queue": "research_events"},
    "apps.research.tasks.calculate_features": {"queue": "research_features"},
    "apps.research.tasks.schedule_research_experiments": {"queue": "celery"},
    "apps.research.tasks.dispatch_research_experiments": {"queue": "celery"},
    "apps.research.tasks.run_single_asset_experiment": {"queue": "research_single_asset"},
    "apps.research.tasks.run_cross_sectional_experiment": {"queue": "research_cross_sectional"},
    "apps.research.tasks.run_allocator_experiment": {"queue": "research_allocators"},
    "apps.research.tasks.run_overlay_experiment": {"queue": "research_overlays"},
    "apps.research.tasks.run_event_experiment": {"queue": "research_cross_sectional"},
    "apps.research.tasks.run_pair_experiment": {"queue": "research_pairs"},
    "apps.research.tasks.score_current_candidates": {"queue": "research_scoring"},
    "apps.research.tasks.warm_recommendation_cache": {"queue": "recommendation_cache"},
    "apps.research.tasks.generate_recommendation_batch": {"queue": "recommendations"},
}
CELERY_TASK_ROUTES = RESEARCH_TASK_ROUTES
