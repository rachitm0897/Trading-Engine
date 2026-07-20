#!/usr/bin/env python3
"""Public QFS route smoke checks; public probes require no secret values."""

import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BACKEND = "https://qfsplatform.com/trading_eng_backend"
DEFAULT_FRONTEND = "https://qfsplatform.com/trading_eng_frontend"
DEFAULT_GATEWAY = "https://qfsplatform.com/trading_eng_gateway"


def fetch(url, *, timeout, token=""):
    headers = {"Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as result:
        return result.status, result.headers.get("Content-Type", ""), result.read(1024 * 1024)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--frontend", default=DEFAULT_FRONTEND)
    parser.add_argument("--gateway", default=DEFAULT_GATEWAY)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    gateway_token = os.getenv("QFS_GATEWAY_SERVICE_TOKEN", "")
    checks = [
        ("backend health", f"{args.backend.rstrip('/')}/healthz", "json", ""),
        ("backend system", f"{args.backend.rstrip('/')}/api/v1/system/", "json", ""),
        ("backend dashboard alias", f"{args.backend.rstrip('/')}/dashboard", "json", ""),
        ("frontend root", f"{args.frontend.rstrip('/')}/", "html", ""),
        ("frontend dashboard deep link", f"{args.frontend.rstrip('/')}/dashboard", "html", ""),
        ("frontend sessions deep link", f"{args.frontend.rstrip('/')}/ibkr-sessions", "html", ""),
        ("gateway root", f"{args.gateway.rstrip('/')}/", "json", ""),
        ("gateway health", f"{args.gateway.rstrip('/')}/healthz", "json", ""),
    ]
    if gateway_token:
        checks.extend([
            ("gateway protected health", f"{args.gateway.rstrip('/')}/api/v1/health/", "json", gateway_token),
            ("gateway protected session", f"{args.gateway.rstrip('/')}/api/v1/session/", "json", gateway_token),
        ])

    failures = []
    for label, url, kind, token in checks:
        try:
            status, content_type, body = fetch(url, timeout=args.timeout, token=token)
            if status != 200:
                raise ValueError(f"HTTP {status}")
            if kind == "json":
                json.loads(body)
            elif b'<div id="root"></div>' not in body:
                raise ValueError("response is not the frontend application shell")
            print(f"PASS {label}: {url} ({content_type.split(';', 1)[0]})")
        except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
            failures.append(label)
            print(f"FAIL {label}: {url} ({exc})", file=sys.stderr)
    if not gateway_token:
        print("SKIP protected gateway API: set QFS_GATEWAY_SERVICE_TOKEN to enable it")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
