import os
import re

from django.conf import settings


QCH_RUNTIME_VARIABLES = ("QCH_APP_ID", "QCH_API_HOST", "QCH_SERVICE_TOKEN")
PINNED_IMAGE_RE = re.compile(r"^.+@sha256:[0-9a-fA-F]{64}$")
VERSION_TAG_RE = re.compile(r"^.+:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$")
EXAMPLE_ENCRYPTION_KEYS = {"replace-with-a-long-random-encryption-key"}


def _effective_value(name):
    if name in QCH_RUNTIME_VARIABLES and name in os.environ:
        return os.environ[name]
    return getattr(settings, name, "")


def managed_broker_deployment_configuration():
    """Return non-secret availability metadata for managed IB Gateway sessions."""
    required = {
        "BROKER_SESSION_ENCRYPTION_KEY": _effective_value("BROKER_SESSION_ENCRYPTION_KEY"),
        "IBKR_GATEWAY_IMAGE": _effective_value("IBKR_GATEWAY_IMAGE"),
        "QCH_APP_ID": _effective_value("QCH_APP_ID"),
        "QCH_API_HOST": _effective_value("QCH_API_HOST"),
        "QCH_SERVICE_TOKEN": _effective_value("QCH_SERVICE_TOKEN"),
    }
    missing = sorted(name for name, value in required.items() if not str(value or "").strip())
    invalid = []
    image = str(required["IBKR_GATEWAY_IMAGE"] or "").strip()
    tag = image.rsplit(":", 1)[-1].casefold() if ":" in image else ""
    fixed_version_tag = bool(
        image
        and "@sha256:" not in image
        and VERSION_TAG_RE.fullmatch(image)
        and tag != "latest"
    )
    if image and not PINNED_IMAGE_RE.fullmatch(image) and not fixed_version_tag:
        invalid.append("IBKR_GATEWAY_IMAGE")
    encryption_key = str(required["BROKER_SESSION_ENCRYPTION_KEY"] or "").strip().casefold()
    if encryption_key in EXAMPLE_ENCRYPTION_KEYS:
        invalid.append("BROKER_SESSION_ENCRYPTION_KEY")
    invalid.sort()
    available = not missing and not invalid
    return {
        "available": available,
        # Retain the established field for existing API clients.
        "ready": available,
        "missing": missing,
        "invalid": invalid,
    }


class ManagedBrokerGatewayUnavailable(RuntimeError):
    def __init__(self, configuration=None):
        self.configuration = configuration or managed_broker_deployment_configuration()
        super().__init__(
            "Managed IB Gateway is unavailable because QCH configuration is incomplete."
        )


def require_managed_broker_deployment():
    configuration = managed_broker_deployment_configuration()
    if not configuration["available"]:
        raise ManagedBrokerGatewayUnavailable(configuration)
    return configuration


def managed_broker_unavailable_error(configuration=None):
    configuration = configuration or managed_broker_deployment_configuration()
    return {
        "code": "BROKER_GATEWAY_NOT_CONFIGURED",
        "message": "Managed IB Gateway is unavailable because QCH configuration is incomplete.",
        "details": {
            "missing": configuration["missing"],
            "invalid": configuration["invalid"],
        },
    }


def managed_broker_disabled_task_result(configuration=None):
    configuration = configuration or managed_broker_deployment_configuration()
    return {
        "status": "disabled",
        "reason": "BROKER_GATEWAY_NOT_CONFIGURED",
        "broker_deployment": configuration,
    }
