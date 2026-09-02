#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, emit

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the deployed Worker identity without querying D1."
    )
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    if not COMMIT_PATTERN.fullmatch(args.expected_commit):
        raise OpsError("expected commit must be a full SHA-1")

    runtime_target = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    target = runtime_target["managed_services"]["webapp"]
    payload = inspect_deployment_identity(
        base_url=str(target["public_base_url"]),
        expected_commit=args.expected_commit,
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
