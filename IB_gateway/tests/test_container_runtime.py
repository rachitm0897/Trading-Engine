from pathlib import Path


def test_entrypoint_stores_the_configured_novnc_password():
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()

    assert 'x11vnc -storepasswd "$novnc_password"' in entrypoint
    assert "| x11vnc -storepasswd -" not in entrypoint


def test_entrypoint_validates_before_writes_migrations_or_supervisor():
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()

    validation = entrypoint.index("runtime_config.py")
    assert validation < entrypoint.index("mkdir -p")
    assert validation < entrypoint.index("manage.py migrate")
    assert validation < entrypoint.index("supervisord")
    assert 'GATEWAY_DB_PATH="${GATEWAY_DB_PATH:-/data/gateway.sqlite3}"' in entrypoint


def test_entrypoint_only_creates_ibc_config_for_real_adapter():
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()

    assert 'if [ "$BROKER_ADAPTER" = "ib_async" ]' in entrypoint
    assert "python manage.py configure_ibc" in entrypoint
    assert "rm -f /home/ibgateway/ibc/config.ini" in entrypoint


def test_existing_api_path_contract_is_unchanged():
    urls = (Path(__file__).resolve().parents[1] / "config" / "urls.py").read_text()

    for route in ("healthz", "api/v1/", "session/", "orders/", "events/", "market-data/history/"):
        assert route in urls
