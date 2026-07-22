"""Validate and normalize container runtime configuration without starting Django."""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import sys
from collections.abc import Mapping


VALID_BROKER_ADAPTERS = {"ib_async", "mock"}
VALID_IBKR_MODES = {"paper", "live"}
PLACEHOLDER_VALUES = {
    "<password>",
    "<secret>",
    "<token>",
    "change-me",
    "change-me-too",
    "changeme",
    "replace-me",
}
KNOWN_PLACEHOLDER_HASHES = {
    "f2bb58dacc874fec3b553e1eec858314417af6fcce64dd69f3938174d5ac8131",
    "4c5dc9b7708905f77f5e5d16316b5dfb425e68cb326dcd55a860e90a7707031e",
    "9242adafa576c83657aa021a5c7e9fd0c60503c2ae5ff8f502cf58b51abf50c0",
    "4f11327cac97c517854b9b0b86e93c50f03834d805c270cdf8400b8dd39349d3",
    "b0060e76ae3488cac69d2e702fa366537fe241e19382ea731059e758fae07be1",
}
RESTART_TIME = re.compile(r"^(0?[1-9]|1[0-2]):[0-5][0-9] (AM|PM)$")


class RuntimeConfigurationError(ValueError):
    def __init__(self, *, missing=(), invalid=()):
        self.missing = tuple(sorted(set(missing)))
        self.invalid = tuple(sorted(set(invalid)))
        details = []
        if self.missing:
            details.append(f"missing variables: {', '.join(self.missing)}")
        if self.invalid:
            details.append(f"invalid variables: {', '.join(self.invalid)}")
        super().__init__("Gateway runtime configuration error; " + "; ".join(details))


def normalize_broker_adapter(value: object) -> str:
    adapter = str(value or "").strip()
    if adapter not in VALID_BROKER_ADAPTERS:
        raise ValueError("BROKER_ADAPTER")
    return adapter


def _is_missing(value: object) -> bool:
    return not str(value or "").strip()


def _is_placeholder(value: object) -> bool:
    normalized = str(value or "").strip().casefold()
    return (
        normalized in PLACEHOLDER_VALUES
        or hashlib.sha256(normalized.encode("utf-8")).hexdigest() in KNOWN_PLACEHOLDER_HASHES
        or normalized.startswith("replace-me")
        or normalized.startswith("replace-with-")
        or normalized.startswith("change-me")
        or (normalized.startswith("<") and normalized.endswith(">"))
    )


def _positive_integer(environment: Mapping[str, str], name: str, default: str, maximum: int) -> str:
    raw = str(environment.get(name, default) or "").strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(name) from exc
    if value < 1 or value > maximum or raw.startswith("+"):
        raise ValueError(name)
    return str(value)


def validate_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    environment = os.environ if environment is None else environment
    missing: list[str] = []
    invalid: list[str] = []

    try:
        adapter = normalize_broker_adapter(environment.get("BROKER_ADAPTER", "ib_async"))
    except ValueError:
        adapter = ""
        invalid.append("BROKER_ADAPTER")

    required = ["DJANGO_SECRET_KEY", "GATEWAY_SERVICE_TOKEN", "NOVNC_PASSWORD"]
    if adapter == "ib_async":
        required.extend(["IB_USERNAME", "IB_PASSWORD", "IBC_TRADING_MODE"])
    for name in required:
        value = environment.get(name, "")
        if _is_missing(value):
            missing.append(name)
        elif _is_placeholder(value) or "\n" in str(value) or "\r" in str(value):
            invalid.append(name)

    raw_mode = environment.get("IBC_TRADING_MODE", "paper" if adapter == "mock" else "")
    mode = str(raw_mode or "").strip().lower()
    if mode and mode not in VALID_IBKR_MODES:
        invalid.append("IBC_TRADING_MODE")

    normalized: dict[str, str] = {}
    integer_fields = {
        "PORT": ("8080", 65535),
        "IBC_2FA_TIMEOUT": ("180", 86400),
        "IBKR_CLIENT_ID": ("17", 999999),
        "TWS_MAJOR_VRSN": ("1045", 99999),
        "BROKER_REFRESH_SECONDS": ("5", 86400),
    }
    for name, (default, maximum) in integer_fields.items():
        try:
            normalized[name] = _positive_integer(environment, name, default, maximum)
        except ValueError:
            invalid.append(name)

    restart_time = str(environment.get("IBC_AUTO_RESTART_TIME", "11:45 PM") or "").strip().upper()
    if not RESTART_TIME.fullmatch(restart_time):
        invalid.append("IBC_AUTO_RESTART_TIME")
    else:
        normalized["IBC_AUTO_RESTART_TIME"] = restart_time

    if missing or invalid:
        raise RuntimeConfigurationError(missing=missing, invalid=invalid)
    normalized["BROKER_ADAPTER"] = adapter
    normalized["IBC_TRADING_MODE"] = mode
    return normalized


def shell_exports(configuration: Mapping[str, str]) -> str:
    return "\n".join(
        f"export {name}={shlex.quote(value)}" for name, value in sorted(configuration.items())
    )


def main() -> int:
    try:
        configuration = validate_environment()
    except RuntimeConfigurationError as exc:
        print(str(exc), file=sys.stderr)
        return 64
    print(shell_exports(configuration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
