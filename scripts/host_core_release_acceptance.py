#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class AcceptanceError(RuntimeError):
    pass


def request_json(url: str, *, timeout_seconds: float = 30) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Accept": "application/json",
            "User-Agent": "wechat-on-airflow-host-core-acceptance/1.0",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=timeout_seconds)
        status = response.status
        raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except urllib.error.URLError as exc:
        raise AcceptanceError(f"request failed for {url}: {exc.reason}") from exc
    if status != 200:
        raise AcceptanceError(f"{url} returned HTTP {status}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcceptanceError(f"{url} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise AcceptanceError(f"{url} returned a non-object JSON payload")
    return payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _venue_timestamp(venue: dict[str, Any]) -> datetime | None:
    for key in ("lastInspectionAt", "last_inspection_at", "updatedAt", "updated_at"):
        parsed = _parse_timestamp(venue.get(key))
        if parsed is not None:
            return parsed
    return None


def validate_cycle(
    *,
    health: dict[str, Any],
    ready: dict[str, Any],
    edge: dict[str, Any],
    bootstrap: dict[str, Any],
    expected_commit: str,
    freshness_minutes: int,
    now: datetime,
    cycle: int,
) -> dict[str, Any]:
    _require(health.get("ok") is True, "host health is not OK")
    _require(health.get("runtime") == "airflow-host", "public API is not host-owned")
    _require(
        health.get("deploymentCommit") == expected_commit,
        "host deployment commit does not match the release commit",
    )
    capabilities = health.get("capabilities")
    _require(isinstance(capabilities, dict), "host capabilities are missing")
    _require(
        capabilities.get("priorityWeatherBypass") is True,
        "priority weather bypass capability is not enabled",
    )
    _require(ready.get("ok") is True, "host readiness is not OK")

    _require(edge.get("ok") is True, "edge health is not OK")
    _require(
        edge.get("runtime") == "cloudflare-stateless-edge",
        "Cloudflare is not running as a stateless edge",
    )
    _require(
        edge.get("deploymentCommit") == expected_commit,
        "edge deployment commit does not match the release commit",
    )
    _require(edge.get("cutover") is True, "edge cutover is not enabled")
    _require(edge.get("quiesced") is False, "edge remains quiesced")
    _require(
        edge.get("migrationEndpoint") is False,
        "migration endpoint remains enabled after cutover",
    )
    _require(
        edge.get("durableBusinessState") == "none",
        "edge still claims durable business state",
    )

    venues = bootstrap.get("venues")
    _require(isinstance(venues, list), "bootstrap venues are missing")
    _require(len(venues) == 26, f"expected 26 venues, found {len(venues)}")

    freshness_cutoff = now - timedelta(minutes=freshness_minutes)
    snapshot: list[tuple[str, str]] = []
    fresh_venues: list[str] = []
    for value in venues:
        if not isinstance(value, dict):
            continue
        venue_id = str(value.get("id") or value.get("venueId") or value.get("venue_id") or "")
        observed_at = _venue_timestamp(value)
        if observed_at is None:
            continue
        snapshot.append((venue_id, observed_at.isoformat()))
        if observed_at >= freshness_cutoff:
            fresh_venues.append(venue_id)

    _require(
        len(fresh_venues) >= 20,
        f"only {len(fresh_venues)} venues have a fresh natural observation",
    )
    digest = hashlib.sha256(
        json.dumps(sorted(snapshot), separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "cycle": cycle,
        "checkedAt": now.isoformat(),
        "commit": expected_commit,
        "hostRuntime": health.get("runtime"),
        "edgeRuntime": edge.get("runtime"),
        "venueCount": len(venues),
        "freshVenueCount": len(fresh_venues),
        "snapshotDigest": digest,
    }


def run_acceptance(
    *,
    base_url: str,
    expected_commit: str,
    cycles: int,
    interval_seconds: float,
    freshness_minutes: int,
) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    root = base_url.rstrip("/")
    for cycle in range(1, cycles + 1):
        summary = validate_cycle(
            health=request_json(f"{root}/api/healthz"),
            ready=request_json(f"{root}/api/readyz"),
            edge=request_json(f"{root}/api/edge-healthz"),
            bootstrap=request_json(f"{root}/api/bootstrap"),
            expected_commit=expected_commit,
            freshness_minutes=freshness_minutes,
            now=datetime.now(UTC),
            cycle=cycle,
        )
        summaries.append(summary)
        if cycle < cycles:
            time.sleep(interval_seconds)

    distinct_snapshots = {str(summary["snapshotDigest"]) for summary in summaries}
    if cycles > 1 and len(distinct_snapshots) < 2:
        raise AcceptanceError(
            "natural venue observations did not advance during the acceptance window"
        )
    return {
        "ok": True,
        "expectedCommit": expected_commit,
        "cycles": summaries,
        "distinctSnapshotCount": len(distinct_snapshots),
        "syntheticNotificationsSent": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only production acceptance for the Airflow-host notification core"
    )
    parser.add_argument("--base-url", default="https://zacks.claude89757.cc")
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--interval-seconds", type=float, default=90)
    parser.add_argument("--freshness-minutes", type=int, default=20)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    if not COMMIT_PATTERN.fullmatch(arguments.expected_commit):
        raise AcceptanceError("expected commit must be a full SHA-1")
    if arguments.cycles < 1:
        raise AcceptanceError("cycles must be positive")
    if arguments.interval_seconds < 0:
        raise AcceptanceError("interval must not be negative")
    if arguments.freshness_minutes < 1:
        raise AcceptanceError("freshness window must be positive")

    result = run_acceptance(
        base_url=arguments.base_url,
        expected_commit=arguments.expected_commit,
        cycles=arguments.cycles,
        interval_seconds=arguments.interval_seconds,
        freshness_minutes=arguments.freshness_minutes,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if arguments.output:
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True))
        raise SystemExit(1) from exc
