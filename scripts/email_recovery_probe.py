"""Bounded email recovery probe, executed only in the existing API container.

Snapshot uses SELECTs and never calls ensure_schema. Mutations share the
established delivery fence, compare the exact previously observed control row,
and preserve the deployment, WeChat, queue and release-acceptance state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from wechat_airflow.host_core.control import DELIVERY_LOCK
from wechat_airflow.host_core.database import SCHEMA_REVISION, get_engine
from wechat_airflow.host_core.release_checkpoint import migration_reconciled
from wechat_airflow.host_core.settings import load_tencent_email_settings

STATE_COLUMNS = (
    "deployment_commit, delivery_enabled, wechat_enabled, activated_at, updated_at, phase"
)
STATUS_NAMES = frozenset(
    {
        "pending",
        "retry",
        "processing",
        "dispatching",
        "submitted",
        "delivered",
        "failed",
        "submission_unknown",
        "delivery_unknown",
        "expired",
        "suppressed",
        "cancelled",
    }
)


class RecoveryRefused(RuntimeError):
    """A public-safe guard failure; never include database or secret values."""


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError) as exc:
        raise RecoveryRefused("invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise RecoveryRefused("timezone_required")
    return parsed.astimezone(UTC)


def timestamp(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value is not None else None


def validate_identity(expected: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise RecoveryRefused("exact_runtime_commit_required")
    if os.environ.get("DEPLOYMENT_COMMIT") != expected:
        raise RecoveryRefused("container_runtime_mismatch")


def require_schema(connection: Any) -> None:
    exists = connection.execute(text("SELECT to_regclass('zacks.schema_versions')")).scalar_one()
    if exists is None:
        raise RecoveryRefused("schema_fingerprint_missing")
    current = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM zacks.schema_versions WHERE version=:revision)"),
        {"revision": SCHEMA_REVISION},
    ).scalar_one()
    if current is not True:
        raise RecoveryRefused("schema_fingerprint_mismatch")


def read_state(connection: Any, *, lock: bool = False) -> dict[str, Any]:
    suffix = " FOR UPDATE" if lock else ""
    return dict(
        connection.execute(
            text(f"SELECT {STATE_COLUMNS} FROM zacks.runtime_control WHERE singleton=true{suffix}")
        )
        .mappings()
        .one()
    )


def state_summary(state: dict[str, Any]) -> dict[str, Any]:
    phase = state["phase"]
    return {
        "deploymentCommit": state["deployment_commit"],
        "deliveryEnabled": state["delivery_enabled"],
        "wechatEnabled": state["wechat_enabled"],
        "activatedAt": timestamp(state["activated_at"]),
        "updatedAt": timestamp(state["updated_at"]),
        "phase": phase if phase in {"prepared", "active", "paused"} else "other",
    }


def migration_complete(connection: Any) -> bool:
    row = (
        connection.execute(
            text(
                "SELECT imported_at, details FROM zacks.migration_state "
                "WHERE source='cloudflare-d1'"
            )
        )
        .mappings()
        .first()
    )
    return bool(row and row["imported_at"] is not None and migration_reconciled(row["details"]))


def heartbeat_summary(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    mode = details.get("mode")
    owner = details.get("owner")
    commit = row["deployment_commit"]
    result = {
        "deploymentCommit": commit if re.fullmatch(r"[0-9a-f]{40}", str(commit)) else "unknown",
        "healthy": row["healthy"] is True,
        "updatedAt": timestamp(row["updated_at"]),
        "mode": mode if mode in {"active", "shadow", "airflow_host", "paused"} else None,
        "owner": owner if type(owner) is bool else None,
    }
    for key in ("system", "subscriber", "reconciled"):
        count = details.get(key)
        if type(count) is int and count >= 0:
            result[key] = count
    return result


def outbox_summary(connection: Any, table: str, since: datetime) -> dict[str, Any]:
    if table not in {"notification_outbox", "system_email_outbox"}:
        raise RecoveryRefused("invalid_outbox")
    statuses: dict[str, int] = {}
    for row in connection.execute(
        text(f"SELECT status, count(*) AS count FROM zacks.{table} GROUP BY status")
    ).mappings():
        name = row["status"] if row["status"] in STATUS_NAMES else "other"
        statuses[name] = statuses.get(name, 0) + int(row["count"])
    if table == "notification_outbox":
        expiry = "created_at < now() - interval '15 minutes'"
        message_column = "message_id"
    else:
        expiry = (
            "COALESCE(expires_at, CASE WHEN email_type='verification' "
            "THEN created_at + interval '10 minutes' ELSE created_at + interval '1 day' END) <= now()"
        )
        message_column = "provider_message_id"
    old_active = connection.execute(
        text(
            f"SELECT count(*) FROM zacks.{table} "
            f"WHERE status IN ('pending','retry','processing') AND ({expiry})"
        )
    ).scalar_one()
    identity = f"COALESCE('provider:' || {message_column}, 'row:' || id)"
    counts = (
        connection.execute(
            text(f"""
                SELECT
                    count(DISTINCT {identity}) FILTER (
                        WHERE submitted_at >= :since
                    ) AS submitted,
                    count(DISTINCT {identity}) FILTER (
                        WHERE submitted_at >= :since AND delivered_at >= :since
                          AND status='delivered'
                    ) AS delivered,
                    count(DISTINCT {identity}) FILTER (
                        WHERE status='failed' AND updated_at >= :since
                    ) AS failed,
                    count(DISTINCT {identity}) FILTER (
                        WHERE status IN ('submission_unknown','delivery_unknown')
                          AND updated_at >= :since
                    ) AS unknown
                FROM zacks.{table}
            """),
            {"since": since},
        )
        .mappings()
        .one()
    )
    return {
        "statuses": statuses,
        "oldActiveBacklog": int(old_active),
        "since": timestamp(since),
        "naturalEmail": {
            key: int(counts[key]) for key in ("submitted", "delivered", "failed", "unknown")
        },
    }


def snapshot(expected: str, since: str = "") -> dict[str, Any]:
    validate_identity(expected)
    with get_engine().connect() as connection:
        connection.execute(text("SET TRANSACTION READ ONLY"))
        connection.execute(text("SET LOCAL statement_timeout = '20s'"))
        require_schema(connection)
        state = read_state(connection)
        if state["deployment_commit"] != expected:
            raise RecoveryRefused("control_runtime_mismatch")
        now = connection.execute(text("SELECT now()")).scalar_one()
        start = parse_timestamp(since) if since else state["updated_at"]
        migration = migration_complete(connection)
        heartbeats = {
            row["component"]: dict(row)
            for row in connection.execute(
                text(
                    "SELECT component, deployment_commit, healthy, updated_at, details "
                    "FROM zacks.runtime_heartbeats WHERE component IN "
                    "('zacks-notification-worker','zacks-wechat-worker')"
                )
            ).mappings()
        }
        fresh = 0
        unhealthy = []
        for row in connection.execute(
            text("SELECT venue_id, healthy, last_inspection_at FROM zacks.venue_status")
        ).mappings():
            healthy = bool(
                row["healthy"]
                and row["last_inspection_at"] is not None
                and row["last_inspection_at"] > now - timedelta(minutes=10)
            )
            if healthy:
                fresh += 1
            elif re.fullmatch(r"[a-z0-9_]{1,64}", str(row["venue_id"])):
                unhealthy.append(row["venue_id"])
        outboxes = {
            table: outbox_summary(connection, table, start)
            for table in ("notification_outbox", "system_email_outbox")
        }
    try:
        load_tencent_email_settings()
        email_configuration = True
    except Exception:
        email_configuration = False
    return {
        "ok": True,
        "generatedAt": timestamp(now),
        "state": state_summary(state),
        "schemaReady": True,
        "emailConfiguration": email_configuration,
        "migrationComplete": migration,
        "everActivated": state["activated_at"] is not None,
        "heartbeat": heartbeat_summary(heartbeats.get("zacks-notification-worker")),
        "wechatHeartbeat": heartbeat_summary(heartbeats.get("zacks-wechat-worker")),
        "freshVenueCount": fresh,
        "unhealthyVenueIds": sorted(unhealthy),
        "outboxes": outboxes,
        "naturalEmail": outboxes["notification_outbox"]["naturalEmail"],
        "naturalSystemEmail": outboxes["system_email_outbox"]["naturalEmail"],
    }


def mutate(expected: str, operation: str, expected_updated_at: str) -> dict[str, Any]:
    validate_identity(expected)
    if operation not in {"enable", "pause"}:
        raise RecoveryRefused("invalid_operation")
    previous_timestamp = parse_timestamp(expected_updated_at)
    enable = operation == "enable"
    with get_engine().begin() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '45s'"))
        connection.execute(text("SET LOCAL statement_timeout = '60s'"))
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DELIVERY_LOCK})
        require_schema(connection)
        state = read_state(connection, lock=True)
        if state["deployment_commit"] != expected:
            raise RecoveryRefused("control_runtime_mismatch")
        if state["wechat_enabled"] is not False:
            raise RecoveryRefused("wechat_must_remain_disabled")
        if state["updated_at"] != previous_timestamp:
            raise RecoveryRefused("control_state_changed")
        if state["delivery_enabled"] is not (not enable):
            raise RecoveryRefused("unexpected_delivery_state")
        if enable:
            if state["activated_at"] is None or not migration_complete(connection):
                raise RecoveryRefused("verified_activation_checkpoint_required")
            load_tencent_email_settings()
        updated = (
            connection.execute(
                text(f"""
                    UPDATE zacks.runtime_control
                    SET delivery_enabled=:enabled, phase=:phase, updated_at=clock_timestamp()
                    WHERE singleton=true AND deployment_commit=:commit
                      AND wechat_enabled=false AND updated_at=:previous_timestamp
                      AND delivery_enabled=:previous_enabled
                    RETURNING {STATE_COLUMNS}
                """),
                {
                    "enabled": enable,
                    "phase": "active" if enable else "paused",
                    "commit": expected,
                    "previous_timestamp": previous_timestamp,
                    "previous_enabled": not enable,
                },
            )
            .mappings()
            .one_or_none()
        )
        if updated is None:
            raise RecoveryRefused("control_state_changed")
        result = state_summary(dict(updated))
    return {"ok": True, "operation": operation, "updatedAt": result["updatedAt"], "state": result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_runtime_sha")
    parser.add_argument("operation", choices=("snapshot", "enable", "pause"))
    parser.add_argument("expected_updated_at", nargs="?", default="")
    parser.add_argument("since", nargs="?", default="")
    args = parser.parse_args()
    try:
        if args.operation == "snapshot":
            result = snapshot(args.expected_runtime_sha, args.since)
        else:
            result = mutate(args.expected_runtime_sha, args.operation, args.expected_updated_at)
    except Exception as exc:
        error = {"ok": False, "errorType": type(exc).__name__}
        if isinstance(exc, RecoveryRefused):
            error["reason"] = str(exc)
        print(json.dumps(error))
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
