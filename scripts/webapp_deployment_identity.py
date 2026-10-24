#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, emit

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
Inspector = Callable[..., dict[str, Any]]


def request_json(url: str, *, timeout_seconds: float = 15) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "wechat-on-airflow-webapp-identity/1.0",
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


def evaluate_deployment_identity(
    status: int,
    payload: Any,
    expected_commit: str,
) -> dict[str, Any]:
    checks = {
        "health_http_ok": status == 200,
        "service_healthy": isinstance(payload, dict) and payload.get("ok") is True,
        "priority_weather_bypass_enabled": isinstance(payload, dict)
        and isinstance(payload.get("capabilities"), dict)
        and payload["capabilities"].get("priorityWeatherBypass") is True,
        "exact_deployment_commit": isinstance(payload, dict)
        and payload.get("deploymentCommit") == expected_commit,
    }
    return {
        "ok": all(checks.values()),
        "expected_commit": expected_commit,
        "deployed_commit": payload.get("deploymentCommit") if isinstance(payload, dict) else None,
        "d1_checked": False,
        "checks": checks,
    }


def inspect_deployment_identity(*, base_url: str, expected_commit: str) -> dict[str, Any]:
    status, payload = request_json(f"{base_url.rstrip('/')}/api/healthz")
    return evaluate_deployment_identity(status, payload, expected_commit)


def deployment_is_propagating(payload: dict[str, Any]) -> bool:
    checks = payload.get("checks")
    if not isinstance(checks, dict) or checks.get("exact_deployment_commit") is not False:
        return False
    other_checks = [value for name, value in checks.items() if name != "exact_deployment_commit"]
    return bool(other_checks) and all(value is True for value in other_checks)


def wait_for_deployment_identity(
    *,
    base_url: str,
    expected_commit: str,
    propagation_timeout_seconds: float,
    retry_interval_seconds: float,
    inspector: Inspector = inspect_deployment_identity,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    deadline = monotonic() + propagation_timeout_seconds
    attempts = 0
    while True:
        attempts += 1
        payload = inspector(base_url=base_url, expected_commit=expected_commit)
        payload = {**payload, "attempts": attempts}
        if payload["ok"] or not deployment_is_propagating(payload):
            return payload
        remaining = deadline - monotonic()
        if remaining <= 0:
            return payload
        sleeper(min(retry_interval_seconds, remaining))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the deployed Worker identity without querying D1."
    )
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--propagation-timeout-seconds", type=float, default=90)
    parser.add_argument("--retry-interval-seconds", type=float, default=2)
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
    payload = wait_for_deployment_identity(
        base_url=str(target["public_base_url"]),
        expected_commit=args.expected_commit,
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
        print(f"webapp-deployment-identity: {exc}")
        raise SystemExit(1) from exc
