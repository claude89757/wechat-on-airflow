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
    other_checks = [
        value
        for name, value in checks.items()
        if name not in {"exact_deployment_commit", "priority_weather_bypass_enabled"}
    ]
    return bool(other_checks) and all(value is True for value in other_checks)


def inspect_production(
    *,
    base_url: str,
    expected_commit: str,
    expected_venue_count: int,
    stateless_edge: bool = False,
) -> dict[str, Any]:
    health_status, health = request_json(f"{base_url}/api/healthz")
    bootstrap_status, bootstrap = request_json(f"{base_url}/api/bootstrap")
    observation_status, _ = request_json(
        f"{base_url}/api/internal/observations",
        method="POST",
        payload={},
    )
    edge_status = 0
    edge: Any = None
    if stateless_edge:
        edge_status, edge = request_json(f"{base_url}/api/edge-healthz")

    venues = bootstrap.get("venues", []) if isinstance(bootstrap, dict) else []
    identity_payload = edge if stateless_edge else health
    checks = {
        "health_http_ok": health_status == 200,
        "service_healthy": isinstance(health, dict) and health.get("ok") is True,
        "priority_weather_bypass_enabled": isinstance(health, dict)
        and isinstance(health.get("capabilities"), dict)
        and health["capabilities"].get("priorityWeatherBypass") is True,
        "exact_deployment_commit": isinstance(identity_payload, dict)
        and identity_payload.get("deploymentCommit") == expected_commit,
        "bootstrap_http_ok": bootstrap_status == 200,
        "expected_venue_count": isinstance(venues, list) and len(venues) == expected_venue_count,
        "bootstrap_contains_no_email": not contains_email(bootstrap),
        "observation_requires_authentication": observation_status == 401,
    }
    if stateless_edge:
        checks.update(
            {
                "edge_health_http_ok": edge_status == 200,
                "edge_service_healthy": isinstance(edge, dict) and edge.get("ok") is True,
                "stateless_edge_runtime": isinstance(edge, dict)
                and edge.get("runtime") == "cloudflare-stateless-edge",
                "edge_has_no_durable_business_state": isinstance(edge, dict)
                and edge.get("durableBusinessState") == "none",
                "host_runtime_airflow": isinstance(health, dict)
                and health.get("runtime") == "airflow-host",
                "edge_cutover_enabled": isinstance(edge, dict) and edge.get("cutover") is True,
                "edge_not_quiesced": isinstance(edge, dict) and edge.get("quiesced") is False,
                "migration_endpoint_disabled": isinstance(edge, dict)
                and edge.get("migrationEndpoint") is False,
            }
        )
    return {
        "ok": all(checks.values()),
        "expected_commit": expected_commit,
        "deployed_commit": (
            identity_payload.get("deploymentCommit")
            if isinstance(identity_payload, dict)
            else None
        ),
        "host_commit": health.get("deploymentCommit") if isinstance(health, dict) else None,
        "edge_commit": edge.get("deploymentCommit") if isinstance(edge, dict) else None,
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
    stateless_edge: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + propagation_timeout_seconds
    while True:
        payload = inspect_production(
            base_url=base_url,
            expected_commit=expected_commit,
            expected_venue_count=expected_venue_count,
            stateless_edge=stateless_edge,
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
    stateless_edge = target.get("runtime") == "cloudflare_worker_stateless_edge"

    payload = wait_for_production(
        base_url=base_url,
        expected_commit=args.expected_commit,
        expected_venue_count=expected_venue_count,
        propagation_timeout_seconds=args.propagation_timeout_seconds,
        retry_interval_seconds=args.retry_interval_seconds,
        stateless_edge=stateless_edge,
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
