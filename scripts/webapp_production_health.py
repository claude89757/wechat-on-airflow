#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, emit

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout_seconds: float = 15,
) -> tuple[int, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "wechat-on-airflow-webapp-health/1.0",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except urllib.error.URLError as exc:
        raise OpsError(f"web application request failed: {exc.reason}") from exc
    else:
        status = response.status
        raw = response.read()

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpsError(f"web application returned invalid JSON with HTTP {status}") from exc
    return status, value


def contains_email(value: Any) -> bool:
    if isinstance(value, str):
        return EMAIL_PATTERN.search(value) is not None
    if isinstance(value, dict):
        return any(contains_email(key) or contains_email(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_email(item) for item in value)
    return False


def deployment_is_propagating(payload: dict[str, Any]) -> bool:
    checks = payload.get("checks")
    if not isinstance(checks, dict) or checks.get("exact_deployment_commit") is not False:
        return False
    other_checks = [value for name, value in checks.items() if name != "exact_deployment_commit"]
    return bool(other_checks) and all(value is True for value in other_checks)


def inspect_production(
    *, base_url: str, expected_commit: str, expected_venue_count: int
) -> dict[str, Any]:
    health_status, health = request_json(f"{base_url}/api/healthz")
    bootstrap_status, bootstrap = request_json(f"{base_url}/api/bootstrap")
    observation_status, _ = request_json(
        f"{base_url}/api/internal/observations",
        method="POST",
        payload={},
    )

    venues = bootstrap.get("venues", []) if isinstance(bootstrap, dict) else []
    checks = {
        "health_http_ok": health_status == 200,
        "service_healthy": isinstance(health, dict) and health.get("ok") is True,
        "exact_deployment_commit": isinstance(health, dict)
        and health.get("deploymentCommit") == expected_commit,
        "bootstrap_http_ok": bootstrap_status == 200,
        "expected_venue_count": isinstance(venues, list) and len(venues) == expected_venue_count,
        "bootstrap_contains_no_email": not contains_email(bootstrap),
        "observation_requires_authentication": observation_status == 401,
    }
    return {
        "ok": all(checks.values()),
        "expected_commit": expected_commit,
        "deployed_commit": health.get("deploymentCommit") if isinstance(health, dict) else None,
        "venue_count": len(venues) if isinstance(venues, list) else None,
        "checks": checks,
    }


def wait_for_production(
    *,
    base_url: str,
    expected_commit: str,
    expected_venue_count: int,
    propagation_timeout_seconds: float,
    retry_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + propagation_timeout_seconds
    while True:
        payload = inspect_production(
            base_url=base_url,
            expected_commit=expected_commit,
            expected_venue_count=expected_venue_count,
        )
        if payload["ok"] or not deployment_is_propagating(payload):
            return payload
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return payload
        time.sleep(min(retry_interval_seconds, remaining))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only production Web application health check."
    )
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--propagation-timeout-seconds", type=float, default=90)
    parser.add_argument("--retry-interval-seconds", type=float, default=5)
    args = parser.parse_args()

    if not COMMIT_PATTERN.fullmatch(args.expected_commit):
        raise OpsError("expected commit must be a full SHA-1")
    if args.propagation_timeout_seconds < 0:
        raise OpsError("propagation timeout must not be negative")
    if args.retry_interval_seconds <= 0:
        raise OpsError("retry interval must be positive")

    runtime_target = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    target = runtime_target["managed_services"]["webapp"]
    base_url = str(target["public_base_url"]).rstrip("/")
    expected_venue_count = int(target["expected_venue_count"])

    payload = wait_for_production(
        base_url=base_url,
        expected_commit=args.expected_commit,
        expected_venue_count=expected_venue_count,
        propagation_timeout_seconds=args.propagation_timeout_seconds,
        retry_interval_seconds=args.retry_interval_seconds,
    )

    emit(payload, args.format)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"webapp-production-health: {exc}")
        raise SystemExit(1) from exc
