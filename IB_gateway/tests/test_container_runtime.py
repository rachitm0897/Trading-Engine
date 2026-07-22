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


def test_entrypoint_prepares_x11_runtime_before_supervisor():
    entrypoint = (Path(__file__).resolve().parents[1] / "entrypoint.sh").read_text()

    supervisor = entrypoint.index("supervisord")
    for command in (
        "/home/ibgateway/Jts",
        "mkdir -p /data /home/ibgateway/.vnc /home/ibgateway/ibc /home/ibgateway/Jts /tmp/.X11-unix",
        "chown root:root /tmp/.X11-unix",
        "chmod 1777 /tmp/.X11-unix",
        "rm -f /tmp/.X1-lock /tmp/.X11-unix/X1",
    ):
        assert command in entrypoint
        assert entrypoint.index(command) < supervisor


def test_x11_clients_wait_for_display_and_gateway_has_bounded_retries():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    supervisor = (root / "supervisord.conf").read_text(encoding="utf-8")
    wait_script = (root / "wait-for-x.sh").read_text(encoding="utf-8")

    assert "x11-utils" in dockerfile
    assert "wait-for-x.sh" in dockerfile
    assert 'xdpyinfo -display "$display"' in wait_script
    for command in (
        "/app/wait-for-x.sh /usr/bin/fluxbox -display :1",
        "/app/wait-for-x.sh /usr/bin/x11vnc -display :1",
        "/app/wait-for-x.sh /app/start-ibgateway.sh",
    ):
        assert command in supervisor

    gateway = supervisor.split("[program:ibgateway]", 1)[1].split("[program:web]", 1)[0]
    assert "autorestart=unexpected" in gateway
    assert "startretries=5" in gateway
    assert "startsecs=10" in gateway
    assert "[unix_http_server]" in supervisor
    assert "serverurl=unix:///tmp/supervisor.sock" in supervisor


def test_existing_api_path_contract_is_unchanged():
    urls = (Path(__file__).resolve().parents[1] / "config" / "urls.py").read_text()

    for route in ("healthz", "readyz", "api/v1/", "diagnostics/", "session/", "orders/", "events/", "market-data/history/"):
        assert route in urls


def test_ibc_launch_uses_detected_gateway_major_without_hard_coded_fallback():
    root = Path(__file__).resolve().parents[1]
    start_script = (root / "start-ibgateway.sh").read_text(encoding="utf-8")
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "ibgateway-version install" in dockerfile
    assert "ibgateway-version verify" in start_script
    assert 'ibcstart.sh "$installed_major"' in start_script
    assert "1045" not in dockerfile
    assert "1045" not in start_script


def test_docker_healthcheck_uses_liveness_not_readiness():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")

    healthcheck = next(line for line in dockerfile.splitlines() if line.startswith("HEALTHCHECK "))
    assert "/healthz" in healthcheck
    assert "/readyz" not in healthcheck
