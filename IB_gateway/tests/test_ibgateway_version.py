from pathlib import Path

import pytest

from ibgateway_version import (
    GatewayVersionError,
    detect_installed_gateway,
    validate_expected_major,
)


def gateway_installation(root: Path, major: str) -> Path:
    installation = root / "gateway"
    jars = installation / "jars"
    jars.mkdir(parents=True)
    (jars / f"jts4launch-{major}.jar").touch()
    return installation


def test_detects_installed_gateway_major_from_launcher_jar(tmp_path):
    installation = gateway_installation(tmp_path, "1047")

    detected = detect_installed_gateway(tmp_path)

    assert detected.major == "1047"
    assert detected.directory == installation.resolve()


def test_detection_rejects_multiple_installed_majors(tmp_path):
    gateway_installation(tmp_path / "first", "1045")
    gateway_installation(tmp_path / "second", "1047")

    with pytest.raises(GatewayVersionError, match="multiple installed IB Gateway majors"):
        detect_installed_gateway(tmp_path)


def test_configured_major_must_match_detected_installation():
    assert validate_expected_major("1047", "1047") == "1047"
    assert validate_expected_major("1047", "") == "1047"

    with pytest.raises(GatewayVersionError, match="does not match TWS_MAJOR_VRSN"):
        validate_expected_major("1047", "1045")


def test_missing_launcher_jar_fails_clearly(tmp_path):
    with pytest.raises(GatewayVersionError, match="could not detect an installed IB Gateway major"):
        detect_installed_gateway(tmp_path)
