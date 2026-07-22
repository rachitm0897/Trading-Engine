#!/usr/bin/env python3
"""Public smoke checks for the two QFS applications."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BACKEND = "https://qfsplatform.com/trading_eng_backend"
DEFAULT_FRONTEND = "https://qfsplatform.com/trading_eng_frontend"
def fetch(url, *, timeout):
    headers = {"Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as result:
        return result.status, result.headers, result.read(1024 * 1024), result.geturl()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", default=DEFAULT_BACKEND)
    parser.add_argument("--frontend", default=DEFAULT_FRONTEND)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    backend = args.backend.rstrip("/")
    frontend = args.frontend.rstrip("/")
    checks = [
        ("backend base", backend, "json"),
        ("backend health", f"{backend}/healthz", "json"),
        ("backend readiness", f"{backend}/readyz", "json"),
        ("backend system", f"{backend}/api/v1/system/", "json"),
        ("backend sessions", f"{backend}/api/v1/broker-sessions/", "json"),
        ("frontend exact-base redirect", frontend, "redirected-html"),
        ("frontend root", f"{frontend}/", "html"),
        ("frontend dashboard deep link", f"{frontend}/dashboard", "html"),
        ("frontend sessions deep link", f"{frontend}/ibkr-sessions", "html"),
        ("frontend runtime config", f"{frontend}/runtime-config.js", "runtime"),
        ("frontend health", f"{frontend}/healthz", "health"),
    ]

    failures = []
    for label, url, kind in checks:
        try:
            status, headers, body, final_url = fetch(url, timeout=args.timeout)
            if status != 200:
                raise ValueError(f"HTTP {status}")
            if kind == "json":
                json.loads(body)
            elif kind in {"html", "redirected-html"} and b'<div id="root"></div>' not in body:
                raise ValueError("response is not the frontend application shell")
            if kind == "redirected-html" and final_url.rstrip("/") != frontend:
                raise ValueError(f"unexpected redirect target {final_url}")
            if kind == "redirected-html" and not final_url.endswith("/"):
                raise ValueError("exact frontend base did not redirect to a trailing slash")
            if kind == "runtime":
                if b"https://qfsplatform.com/trading_eng_backend/api/v1" not in body:
                    raise ValueError("runtime Backend URL is incorrect")
                if "no-store" not in headers.get("Cache-Control", "").lower():
                    raise ValueError("runtime config is cacheable")
            if kind == "health" and body.strip() != b"ok":
                raise ValueError("unexpected frontend health response")
            content_type = headers.get("Content-Type", "")
            print(f"PASS {label}: {url} ({content_type.split(';', 1)[0]})")
        except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
            failures.append(label)
            print(f"FAIL {label}: {url} ({exc})", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
