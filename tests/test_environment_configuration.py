import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _removed_variables():
    # Keep the complete obsolete names out of the test source so the
    # repository-wide zero-reference assertion includes this file.
    return (
        "LIVE_BAR_" + "TIMEOUT_MULTIPLIER",
        "LIVE_BAR_" + "TIMEOUT_GRACE_SECONDS",
        "LIVE_BAR_" + "TIMEOUT_MIN_SECONDS",
        "VITE_API_" + "BASE_URL",
        "RESEARCH_DAILY_" + "PROVIDER",
        "USE_" + "SQLITE",
    )


def test_removed_environment_variables_have_no_tracked_references():
    if not (REPOSITORY_ROOT / ".git").exists():
        pytest.skip("full tracked repository is not available in this test image")
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8").split("\0")
    references = {}
    for relative_path in filter(None, tracked):
        try:
            contents = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for variable in _removed_variables():
            if variable in contents:
                references.setdefault(variable, []).append(relative_path)
    assert references == {}


def test_compose_renders_one_static_gateway_vnc_password_source():
    if shutil.which("docker") is None or not (
        REPOSITORY_ROOT / "docker-compose.yml"
    ).exists():
        pytest.skip("Docker Compose source is not available in this test image")
    environment = os.environ.copy()
    environment.update(
        {
            "LOCAL_PAPER_GATEWAY_DJANGO_SECRET_KEY": "dummy-django-secret",
            "LOCAL_PAPER_GATEWAY_SERVICE_TOKEN": "dummy-service-token",
            "LOCAL_PAPER_GATEWAY_NOVNC_PASSWORD": "dummy-vnc-password",
        }
    )
    rendered = subprocess.run(
        [
            "docker",
            "compose",
            "--profile",
            "paper-ibkr",
            "--env-file",
            ".env.example",
            "config",
            "--format",
            "json",
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    services = json.loads(rendered.stdout)["services"]
    backend = services["backend"]["environment"]
    gateway = services["paper-ibkr-gateway"]["environment"]

    assert backend["LOCAL_PAPER_GATEWAY_NOVNC_PASSWORD"] == "dummy-vnc-password"
    assert gateway["NOVNC_PASSWORD"] == "dummy-vnc-password"
    assert gateway["GATEWAY_SERVICE_TOKEN"] == "dummy-service-token"
    assert gateway["GATEWAY_SERVICE_TOKEN"] != gateway["NOVNC_PASSWORD"]
