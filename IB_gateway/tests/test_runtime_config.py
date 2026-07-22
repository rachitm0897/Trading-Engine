from pathlib import Path

import pytest

from runtime_config import RuntimeConfigurationError, validate_environment


def valid_real_environment(**updates):
    environment = {
        "BROKER_ADAPTER": "ib_async",
        "DJANGO_SECRET_KEY": "real-mode-django-secret-for-unit-tests",
        "GATEWAY_SERVICE_TOKEN": "real-mode-service-token-for-unit-tests",
        "NOVNC_PASSWORD": "vnc-unit",
        "IB_USERNAME": "ib-user",
        "IB_PASSWORD": "ib-password",
        "IBC_TRADING_MODE": "paper",
    }
    environment.update(updates)
    return environment


def test_real_mode_requires_every_session_and_security_variable():
    with pytest.raises(RuntimeConfigurationError) as error:
        validate_environment({"BROKER_ADAPTER": "ib_async"})

    assert set(error.value.missing) == {
        "DJANGO_SECRET_KEY",
        "GATEWAY_SERVICE_TOKEN",
        "NOVNC_PASSWORD",
        "IB_USERNAME",
        "IB_PASSWORD",
        "IBC_TRADING_MODE",
    }


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("DJANGO_SECRET_KEY", "gateway-test-secret"),
        ("GATEWAY_SERVICE_TOKEN", "test-token"),
        ("NOVNC_PASSWORD", "replace-me"),
        ("IB_PASSWORD", "replace-with-a-real-password"),
    ],
)
def test_real_mode_rejects_known_placeholders_without_echoing_them(name, value):
    with pytest.raises(RuntimeConfigurationError) as error:
        validate_environment(valid_real_environment(**{name: value}))

    assert error.value.invalid == (name,)
    assert value not in str(error.value)


def test_mock_mode_needs_explicit_security_but_not_ibkr_credentials():
    configuration = validate_environment(
        {
            "BROKER_ADAPTER": "mock",
            "DJANGO_SECRET_KEY": "mock-mode-django-secret-for-unit-tests",
            "GATEWAY_SERVICE_TOKEN": "mock-mode-service-token-for-unit-tests",
            "NOVNC_PASSWORD": "mock-vnc",
        }
    )

    assert configuration["BROKER_ADAPTER"] == "mock"
    assert configuration["IBC_TRADING_MODE"] == "paper"


@pytest.mark.parametrize("adapter", ["MOCK", "demo", "", "ib-sync"])
def test_invalid_adapter_fails(adapter):
    environment = valid_real_environment(BROKER_ADAPTER=adapter)
    with pytest.raises(RuntimeConfigurationError) as error:
        validate_environment(environment)
    assert "BROKER_ADAPTER" in error.value.invalid


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("PORT", "0"),
        ("PORT", "65536"),
        ("IBC_2FA_TIMEOUT", "1.5"),
        ("IBKR_CLIENT_ID", "-1"),
        ("TWS_MAJOR_VRSN", "not-a-number"),
        ("BROKER_REFRESH_SECONDS", "0"),
        ("IBC_AUTO_RESTART_TIME", "25:99"),
    ],
)
def test_invalid_numeric_and_timeout_configuration_fails_by_variable_name(name, value):
    with pytest.raises(RuntimeConfigurationError) as error:
        validate_environment(valid_real_environment(**{name: value}))
    assert name in error.value.invalid
    assert value not in str(error.value)


def test_backend_child_environment_contract_validates_without_public_base_path():
    environment = valid_real_environment(PORT="8080")

    configuration = validate_environment(environment)

    assert configuration["PORT"] == "8080"
    assert "TWS_MAJOR_VRSN" not in configuration
    assert "APP_BASE_PATH" not in configuration


def test_optional_gateway_major_is_only_a_validated_runtime_assertion():
    configuration = validate_environment(valid_real_environment(TWS_MAJOR_VRSN="1047"))

    assert configuration["TWS_MAJOR_VRSN"] == "1047"


def test_dockerfile_is_registry_neutral_and_has_one_public_port():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    expose_lines = [line.strip() for line in dockerfile.splitlines() if line.strip().startswith("EXPOSE ")]

    assert "COPY .env.example" not in dockerfile
    assert "COPY . ." not in dockerfile
    assert "qfsplatform.com" not in dockerfile
    assert "APP_BASE_PATH" not in dockerfile
    assert expose_lines == ["EXPOSE 8080"]
    assert 'ENTRYPOINT ["/usr/bin/tini", "--", "./entrypoint.sh"]' in dockerfile
    assert "Unsupported target architecture" in dockerfile


def test_docker_context_excludes_runtime_secrets_databases_and_test_fixtures():
    dockerignore = (Path(__file__).resolve().parents[1] / ".dockerignore").read_text(encoding="utf-8")

    for pattern in (".env", ".env.*", "*.sqlite3", "**/.vnc", "**/ibc/config.ini", "tests"):
        assert pattern in dockerignore.splitlines()


def test_mock_start_script_never_invokes_ibc():
    start_script = (Path(__file__).resolve().parents[1] / "start-ibgateway.sh").read_text(encoding="utf-8")
    mock_branch = start_script.split("\nfi", 1)[0]

    assert "sleep infinity" in mock_branch
    assert "ibcstart.sh" not in mock_branch
