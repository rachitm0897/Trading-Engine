# Environment variable inventory

This inventory covers tracked Compose files, component example files, Python
environment reads, Dockerfiles, shell entrypoints, Vite, Nginx, Kafka, Flink,
tests, CI, and deployment documentation. Every variable in a row has the
classification shown for that row.

| Classification | Variables | Runtime consumer |
| --- | --- | --- |
| Required secret | `DJANGO_SECRET_KEY`, `BROKER_SESSION_ENCRYPTION_KEY` | Backend Django and broker-session encryption |
| Required secret | `LOCAL_PAPER_GATEWAY_DJANGO_SECRET_KEY`, `LOCAL_PAPER_GATEWAY_SERVICE_TOKEN`, `LOCAL_PAPER_GATEWAY_NOVNC_PASSWORD` | Root Compose; mapped independently to the static Gateway and Backend |
| Required secret | `QCH_SERVICE_TOKEN` | Backend QCH child-container client |
| Required secret | `GATEWAY_SERVICE_TOKEN`, `NOVNC_PASSWORD`, `IB_PASSWORD` | Private Gateway authentication, x11vnc, and IBC |
| Required deployment/runtime configuration | `IB_USERNAME` | IBC login identity for a real Gateway session |
| Required secret | `FINNHUB_API_KEY`, `FINNHUB_ENCRYPTION_KEY` | Backend Finnhub provider configuration |
| Required deployment/runtime configuration | `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Django database and Celery |
| Required deployment/runtime configuration | `QCH_APP_ID`, `QCH_API_HOST`, `IBKR_GATEWAY_IMAGE` | Managed QCH Gateway provisioning |
| Required deployment/runtime configuration | `APP_BASE_PATH`, `PUBLIC_BASE_URL`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `PORT`, `FORWARDED_ALLOW_IPS` | Backend public routing, Django, Gunicorn, and Nginx |
| Required deployment/runtime configuration | `BACKEND_API_URL` | Frontend startup-generated `runtime-config.js` |
| Valid optional operator override | `DJANGO_DEBUG`, `ALLOW_LIVE_TRADING`, `GLOBAL_KILL_SWITCH` | Backend deployment and trading safety policy; Compose pins live trading off |
| Valid optional operator override | `STRATEGY_EVALUATION_MAX_ATTEMPTS`, `STRATEGY_EVALUATION_RETRY_BASE_SECONDS`, `STRATEGY_EVALUATION_RETRY_MAX_SECONDS`, `STRATEGY_EVALUATION_CLAIM_TIMEOUT_SECONDS`, `STRATEGY_EVALUATION_BATCH_SIZE` | Durable strategy-evaluation jobs |
| Valid optional operator override | `PORTFOLIO_TARGET_MAX_AGE_SECONDS`, `PORTFOLIO_TARGET_COORDINATION_DEBOUNCE_SECONDS`, `PORTFOLIO_TARGET_COORDINATION_BATCH_SIZE`, `PORTFOLIO_TARGET_COORDINATION_RETRY_BASE_SECONDS`, `PORTFOLIO_TARGET_COORDINATION_RETRY_MAX_SECONDS` | Portfolio target coordinator |
| Valid optional operator override | `EXECUTION_AVERAGE_VOLUME_WINDOW`, `EXECUTION_REGISTER_ADV_INPUT`, `EXECUTION_ADV_TIMEFRAME`, `ORDER_INTENT_BATCH_SIZE`, `ORDER_INTENT_CLAIM_TIMEOUT_SECONDS`, `BROKER_COMMAND_BATCH_SIZE`, `BROKER_COMMAND_RETRY_BASE_SECONDS`, `BROKER_COMMAND_RETRY_MAX_SECONDS`, `BROKER_COMMAND_CLAIM_TIMEOUT_SECONDS`, `BROKER_COMMAND_MAX_AGE_SECONDS`, `PENDING_INTENT_MAX_AGE_SECONDS` | Strategy inputs and durable execution dispatch |
| Valid optional operator override | `EXECUTION_REQUIRED_FLINK_JOBS`, `EXECUTION_REQUIRED_KAFKA_TOPICS`, `EXECUTION_ACTIVATION_PREFLIGHT_ENABLED`, `EXECUTION_READINESS_HTTP_TIMEOUT_SECONDS`, `EXECUTION_WORKER_HEARTBEAT_STALE_SECONDS`, `GATEWAY_CONNECTIVITY_STALE_SECONDS`, `STRATEGY_JOB_BACKLOG_THRESHOLD`, `TARGET_COORDINATION_BACKLOG_THRESHOLD` | Execution readiness and activation preflight |
| Valid optional operator override | `BROKER_CREDENTIAL_TTL_SECONDS`, `BROKER_SESSION_CREATING_STALE_SECONDS`, `BROKER_SESSION_START_TIMEOUT_SECONDS`, `BROKER_SESSION_HEALTH_TIMEOUT_SECONDS` | Managed broker-session lifecycle |
| Valid optional operator override | `NOVNC_ACCESS_TOKEN_TTL_SECONDS`, `NOVNC_PROXY_CONNECT_TIMEOUT_SECONDS`, `NOVNC_PROXY_IDLE_TIMEOUT_SECONDS`, `NOVNC_PROXY_MAX_BODY_BYTES` | Private Backend noVNC proxy |
| Valid optional operator override | `QCH_REQUEST_TIMEOUT_SECONDS`, `QCH_SUBCONTAINER_NETWORK` | QCH client and child networking |
| Valid optional operator override | `KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_CLIENT_ID`, `KAFKA_ENABLED`, `KAFKA_HEALTH_STALE_SECONDS`, `KAFKA_LAG_DEGRADED_THRESHOLD`, `OUTBOX_PUBLISHER_HEARTBEAT_STALE_SECONDS`, `MARKET_RAW_PRODUCER_HEARTBEAT_STALE_SECONDS`, `MARKET_CONSUMER_HEARTBEAT_STALE_SECONDS` | Backend event bus and readiness |
| Valid optional operator override | `MARKET_PRICE_STALE_SECONDS`, `WARMUP_SAFETY_BARS`, `WARMUP_TIMEOUT_SECONDS`, `FLINK_CHECKPOINT_STALE_SECONDS`, `FLINK_REST_URL` | Market-stream freshness, warm-up, and Flink readiness |
| Valid optional operator override | `FINNHUB_BASE_URL`, `FINNHUB_API_KEY_OVERRIDE_ENABLED`, `FINNHUB_REQUEST_TIMEOUT_SECONDS`, `FINNHUB_MAX_RETRIES`, `FINNHUB_OPERATION_THROTTLE_LIMIT`, `MARKET_DATA_FALLBACK_ENABLED`, `FINNHUB_HISTORICAL_FALLBACK_ENABLED`, `FINNHUB_LIVE_FALLBACK_ENABLED`, `FINNHUB_AUTO_FAILBACK_ENABLED` | Backend Finnhub REST and fallback policy |
| Valid optional operator override | `IBKR_MARKET_DATA_FAILOVER_GRACE_SECONDS`, `FINNHUB_LIVE_STALE_SECONDS`, `FINNHUB_WS_URL`, `FINNHUB_WS_RECONNECT_MAX_SECONDS`, `FINNHUB_ALLOWED_LATENESS_SECONDS`, `FINNHUB_WS_RECONCILE_SECONDS`, `PRIMARY_RECOVERY_CONFIRMATION_EVENTS`, `PRIMARY_PROBE_RETRY_SECONDS`, `FINNHUB_MAPPING_REVALIDATE_SECONDS`, `FINNHUB_SUPPORTED_ASSET_CLASSES` | Live market-data failover and mapping |
| Valid optional operator override | `GATEWAY_HTTP_TIMEOUT_SECONDS`, `GATEWAY_COMMAND_POLL_INTERVAL_SECONDS`, `GATEWAY_COMMAND_TIMEOUT_DEFAULT_SECONDS`, `GATEWAY_COMMAND_TIMEOUT_SEARCH_CONTRACTS_SECONDS`, `GATEWAY_COMMAND_TIMEOUT_QUALIFY_SECONDS`, `GATEWAY_COMMAND_TIMEOUT_HISTORICAL_DATA_SECONDS`, `GATEWAY_COMMAND_TIMEOUT_HISTORICAL_SCHEDULE_SECONDS`, `GATEWAY_SAFE_COMMAND_RETRIES` | Backend Gateway client |
| Valid optional operator override | `GATEWAY_CONTRACT_SEARCH_MAX_RESULTS`, `GATEWAY_IBKR_REQUEST_TIMEOUT_SEARCH_CONTRACTS_SECONDS`, `GATEWAY_IBKR_REQUEST_TIMEOUT_QUALIFY_SECONDS` | Backend-to-Gateway command contract |
| Valid optional operator override | `LOCAL_PAPER_GATEWAY_URL`, `LOCAL_PAPER_GATEWAY_CONTAINER_NAME` | Internal static-session binding; Compose supplies literal service wiring |
| Valid optional operator override | `OPTIMIZATION_THROTTLE_LIMIT`, `EXPENSIVE_OPERATION_THROTTLE_WINDOW_SECONDS` | Expensive Backend API throttling |
| Valid optional operator override | `OUTBOX_RETENTION_DAYS`, `BROKER_SNAPSHOT_RETENTION_DAYS`, `STREAM_HEALTH_RETENTION_DAYS`, `OPERATIONAL_COMPACTION_BATCH_SIZE` | Operational record compaction |
| Valid optional operator override | `RESEARCH_ENABLED`, `RECOMMENDATION_SYSTEM_ENABLED`, `RECOMMENDATION_UNIVERSE_KEY`, `RECOMMENDATION_MAX_STOCKS`, `RECOMMENDATION_MIN_STOCKS`, `RECOMMENDATION_CANDIDATE_POOL_SIZE`, `RECOMMENDATION_MAX_STRATEGIES_PER_STOCK` | Typed recommendation-system configuration |
| Valid optional operator override | `RESEARCH_DAILY_LOOKBACK_YEARS`, `RESEARCH_INTRADAY_LOOKBACK_DAYS`, `RESEARCH_MINIMUM_DAILY_BARS`, `RESEARCH_SCORE_MAX_AGE_DAYS`, `RESEARCH_STALE_SCORE_FALLBACK_DAYS`, `RECOMMENDATION_SNAPSHOT_MAX_AGE_HOURS`, `RESEARCH_MAX_PARALLEL_DATA_TASKS`, `RESEARCH_MAX_PARALLEL_BACKTEST_TASKS`, `RESEARCH_BUNDLE_PATH`, `RESEARCH_ARTIFACT_ROOT` | Research data, scoring, workers, and artifacts |
| Valid optional operator override | `BROKER_ADAPTER`, `IBC_TRADING_MODE`, `IBC_2FA_TIMEOUT`, `IBC_AUTO_RESTART_TIME`, `IBKR_CLIENT_ID`, `TWS_MAJOR_VRSN`, `BROKER_REFRESH_SECONDS` | Gateway runtime validation, IBC, and broker worker |
| Valid optional operator override | `GATEWAY_DB_PATH`, `IBC_CONFIG_PATH`, `WAIT_FOR_X_TIMEOUT_SECONDS`, `DISPLAY` | Gateway SQLite, IBC file generation, and X11 startup |
| Valid optional operator override | `GATEWAY_EVENT_RETENTION_DAYS`, `GATEWAY_HEALTH_RETENTION_DAYS`, `GATEWAY_COMPACTION_SECONDS`, `GATEWAY_COMPACTION_BATCH_SIZE` | Gateway operational compaction |
| Valid optional operator override | `MOCK_BROKER_ACCOUNT_ID`, `MOCK_BROKER_AUTO_FILL`, `MOCK_BROKER_FILL_PRICE`, `MOCK_BROKER_MARKET_HEARTBEAT_SECONDS` | Gateway mock adapter |
| Valid optional operator override | `AUTO_SUBMIT_FLINK_JOBS`, `FLINK_CHECKPOINT_INTERVAL_MS`, `FLINK_CHECKPOINT_TIMEOUT_MS`, `FLINK_PARALLELISM`, `FLINK_PROCESSING_MODE`, `ALLOWED_LATENESS_SECONDS`, `UNKNOWN_CONID_BUFFER_TIMEOUT_MS`, `UNKNOWN_CONID_BUFFER_MAX_EVENTS`, `DEDUPLICATION_STATE_TTL_SECONDS` | Flink entrypoint and jobs |
| Valid optional operator override | `KAFKA_STARTING_OFFSETS`, `KAFKA_STARTING_OFFSETS_MARKET_NORMALIZATION_V2`, `KAFKA_STARTING_OFFSETS_BAR_AGGREGATION_V2`, `KAFKA_STARTING_OFFSETS_INDICATOR_COMPUTATION_V2`, `KAFKA_STARTING_OFFSETS_STALE_PRICE_DETECTION_V1`, `KAFKA_STARTING_OFFSETS_STREAM_HEALTH_V1` | Per-job Kafka recovery policy |
| Build-time configuration | `VITE_APP_BASE_PATH` | Vite asset and React Router base |
| Third-party build contract | `BASE_URL`, `MODE` | Vite-provided built-ins consumed by the React application |
| Third-party runtime contract | `DJANGO_SETTINGS_MODULE` | Django process and test-settings module selection |
| Build-time configuration | `TARGETARCH`, `IBC_VERSION`, `IB_GATEWAY_INSTALLER_URL`, `OCI_SOURCE`, `OCI_VERSION`, `OCI_REVISION`, `OCI_CREATED`, `OCI_TITLE`, `OCI_DESCRIPTION` | Gateway image architecture, dependency, and OCI metadata |
| Build-time configuration | `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED`, `PYTHONPATH`, `DEBIAN_FRONTEND` | Python and image build/runtime behavior |
| Third-party container contract | `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` | PostgreSQL image, health check, and host publishing |
| Third-party container contract | `KAFKA_NODE_ID`, `KAFKA_PROCESS_ROLES`, `KAFKA_LISTENERS`, `KAFKA_ADVERTISED_LISTENERS`, `KAFKA_LISTENER_SECURITY_PROTOCOL_MAP`, `KAFKA_CONTROLLER_LISTENER_NAMES`, `KAFKA_CONTROLLER_QUORUM_VOTERS`, `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR`, `KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR`, `KAFKA_TRANSACTION_STATE_LOG_MIN_ISR`, `KAFKA_AUTO_CREATE_TOPICS_ENABLE`, `CLUSTER_ID` | Apache Kafka container |
| Third-party container contract | `FLINK_PROPERTIES` | Apache Flink container |
| Duplicate alias retained | `BACKEND_APP_BASE_PATH`, `BACKEND_PUBLIC_BASE_URL`, `BACKEND_PORT`, `FRONTEND_PORT` | Root Compose interpolation mapped to component-local names and port publishing |
| Duplicate alias retained | `IBKR_USERNAME`, `IBKR_PASSWORD` | Root operator inputs mapped to the child contract's `IB_USERNAME` and `IB_PASSWORD` |
| Duplicate alias retained | `LOCAL_PAPER_GATEWAY_ADAPTER`, `LOCAL_PAPER_MOCK_ACCOUNT_ID`, `LOCAL_PAPER_MOCK_AUTO_FILL`, `LOCAL_PAPER_MOCK_FILL_PRICE`, `LOCAL_PAPER_MOCK_MARKET_HEARTBEAT_SECONDS` | Root static-paper options mapped to Gateway variables |
| Test-only runtime configuration | `RUN_DOCKER_PAPER_PIPELINE` | Opt-in Docker paper-pipeline test |
| Dead or unused | None | All confirmed dead declarations were removed |
| Obsolete after a removed feature | None | All confirmed obsolete declarations were removed |

Variables supplied only as literal internal Compose values remain in this
inventory because they are real process environment contracts, not operator
options. Defaults do not make the corresponding variables dead.
