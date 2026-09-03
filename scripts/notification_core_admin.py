#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

from wechat_airflow.notification_core.config import load_settings
from wechat_airflow.notification_core.database import ensure_schema
from wechat_airflow.notification_core.repository import service_metrics
from wechat_airflow.notification_core.subscription_sync import synchronize_from_cloudflare

LOCAL_OBSERVATION_URL = "http://zacks-notification-api:8091/api/internal/observations"
CURRENT_URL_VARIABLE = "WEBAPP_OBSERVATION_API_URL"
PREVIOUS_URL_VARIABLE = "ZACKS_CORE_PREVIOUS_OBSERVATION_API_URL"
MODE_VARIABLE = "ZACKS_CORE_DELIVERY_MODE"


def _variable_get(name: str, default: str = "") -> str:
    from airflow.sdk import Variable

    return str(Variable.get(name, default=default) or "").strip()


def _variable_set(name: str, value: str) -> None:
    from airflow.sdk import Variable

    Variable.set(name, value)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def migrate() -> int:
    settings = load_settings()
    ensure_schema(settings)
    _print({"success": True, "operation": "migrate", **service_metrics(settings)})
    return 0


def sync(allow_empty: bool) -> int:
    settings = load_settings()
    ensure_schema(settings)
    summary = synchronize_from_cloudflare(settings)
    count = int(summary.get("subscriptions") or 0)
    if count == 0 and not allow_empty:
        raise RuntimeError("subscription snapshot is empty; use --allow-empty only when verified")
    _print({"success": True, "operation": "sync", **summary})
    return 0


def cutover(allow_empty: bool) -> int:
    settings = load_settings()
    ensure_schema(settings)
    summary = synchronize_from_cloudflare(settings)
    count = int(summary.get("subscriptions") or 0)
    if count == 0 and not allow_empty:
        raise RuntimeError("refusing cutover with an empty subscription snapshot")

    current = _variable_get(CURRENT_URL_VARIABLE)
    if not current:
        raise RuntimeError("current observation URL is not configured")
    if current != LOCAL_OBSERVATION_URL and not _variable_get(PREVIOUS_URL_VARIABLE):
        _variable_set(PREVIOUS_URL_VARIABLE, current)
    _variable_set(CURRENT_URL_VARIABLE, LOCAL_OBSERVATION_URL)
    _variable_set(MODE_VARIABLE, "active")
    _print(
        {
            "success": True,
            "operation": "cutover",
            "observationOwner": "airflow_host",
            "deliveryMode": "active",
            "subscriptions": count,
            "revision": summary.get("revision"),
        }
    )
    return 0


def rollback() -> int:
    previous = _variable_get(PREVIOUS_URL_VARIABLE)
    if not previous:
        raise RuntimeError("no previous observation URL is available")
    _variable_set(MODE_VARIABLE, "shadow")
    _variable_set(CURRENT_URL_VARIABLE, previous)
    _print(
        {
            "success": True,
            "operation": "rollback",
            "observationOwner": "cloudflare",
            "deliveryMode": "shadow",
        }
    )
    return 0


def status() -> int:
    settings = load_settings()
    ensure_schema(settings)
    current = _variable_get(CURRENT_URL_VARIABLE)
    _print(
        {
            "success": True,
            "operation": "status",
            "observationOwner": (
                "airflow_host" if current == LOCAL_OBSERVATION_URL else "cloudflare"
            ),
            "deliveryMode": _variable_get(MODE_VARIABLE, "shadow"),
            **service_metrics(settings),
        }
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Operate the Airflow-host notification core")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("migrate")
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--allow-empty", action="store_true")
    cutover_parser = subparsers.add_parser("cutover")
    cutover_parser.add_argument("--allow-empty", action="store_true")
    subparsers.add_parser("rollback")
    subparsers.add_parser("status")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.operation == "migrate":
        return migrate()
    if args.operation == "sync":
        return sync(args.allow_empty)
    if args.operation == "cutover":
        return cutover(args.allow_empty)
    if args.operation == "rollback":
        return rollback()
    if args.operation == "status":
        return status()
    raise RuntimeError(f"unsupported operation: {args.operation}")


if __name__ == "__main__":
    raise SystemExit(main())
