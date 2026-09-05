"""Read-only business acceptance with explicit, complete, privacy-safe evidence."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text

from .control import runtime_state
from .database import transaction
from .domain import utc_now
from .settings import load_tencent_email_settings
from .wechat_worker import sender_readiness

ROOT = Path(__file__).resolve().parents[3]
COMPONENT_MAX_AGE = {"zacks-notification-worker": 120, "zacks-wechat-worker": 300}


def worker_health(component: str) -> bool:
    with transaction() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT deployment_commit, healthy, updated_at FROM zacks.runtime_heartbeats WHERE component=:component"
                ),
                {"component": component},
            )
            .mappings()
            .first()
        )
    return bool(
        row
        and row["healthy"]
        and row["deployment_commit"] == os.environ.get("DEPLOYMENT_COMMIT")
        and row["updated_at"] > utc_now() - timedelta(seconds=COMPONENT_MAX_AGE[component])
    )


def business_report(expected_commit: str, *, require_delivery: bool = False) -> dict[str, Any]:
    state = runtime_state()
    since = state["acceptance_started_at"] or state["deployment_started_at"]
    now = utc_now()
    manifest = yaml.safe_load((ROOT / "config/active-components.yaml").read_text())
    venue_components = [
        entry
        for entry in manifest["active_dags"]
        if "webapp_observation" in entry.get("notifications", [])
    ]
    auxiliary = [entry for entry in manifest["active_dags"] if entry not in venue_components]
    checks: dict[str, bool] = {
        "exactHostCommit": expected_commit == os.environ.get("DEPLOYMENT_COMMIT"),
        "exactControlCommit": state["deployment_commit"] == expected_commit,
        "acceptanceWindowStarted": state["acceptance_started_at"] is not None,
        "singleHostDeliveryOwner": state["delivery_enabled"] is True,
        "wechatDeliveryEnabled": state["wechat_enabled"] is True,
    }
    api_evidence = state.get("api_acceptance") or {}
    checks["subscriptionApiTransaction"] = (
        api_evidence.get("ok") is True
        and api_evidence.get("complete") is True
        and api_evidence.get("deploymentCommit") == expected_commit
        and api_evidence.get("mode") == "production_transaction_rollback"
        and api_evidence.get("externalTestSends") == 0
    )
    try:
        load_tencent_email_settings()
        checks["emailConfiguration"] = True
    except RuntimeError:
        checks["emailConfiguration"] = False
    with transaction() as connection:
        migration = (
            connection.execute(
                text(
                    "SELECT source_revision, imported_at, details FROM zacks.migration_state WHERE source='cloudflare-d1'"
                )
            )
            .mappings()
            .first()
        )
        proof = migration["details"].get("reconciliation", {}) if migration else {}
        table_proof = {key: value for key, value in proof.items() if isinstance(value, dict)}
        checks["migrationReconciled"] = (
            len(table_proof) == 15
            and proof.get("providerIdentityPreserved") is True
            and all(v.get("sourceCount") == v.get("matchedCount") for v in table_proof.values())
        )
        heartbeats = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT component, deployment_commit, healthy, updated_at FROM zacks.runtime_heartbeats "
                    "WHERE component IN ('zacks-notification-worker','zacks-wechat-worker')"
                )
            ).mappings()
        ]
        for component, age in COMPONENT_MAX_AGE.items():
            rows = [r for r in heartbeats if r["component"] == component]
            checks[component] = bool(
                rows
                and rows[0]["healthy"]
                and rows[0]["deployment_commit"] == expected_commit
                and rows[0]["updated_at"] > now - timedelta(seconds=age)
            )
        venues = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT venue_id, venue_name, healthy, last_inspection_at FROM zacks.venue_status ORDER BY venue_id"
                )
            ).mappings()
        ]
        checks["all26VenueObservations"] = len(venues) == 26 and all(
            row["healthy"]
            and row["last_inspection_at"]
            and row["last_inspection_at"] >= since
            and row["last_inspection_at"] > now - timedelta(minutes=10)
            for row in venues
        )
        scopes = [
            dict(row)
            for row in connection.execute(
                text(
                    "SELECT observation_key, healthy, last_seen_at FROM zacks.observation_state ORDER BY observation_key"
                )
            ).mappings()
        ]
        checks["allObservationScopesHealthy"] = bool(scopes) and all(
            row["healthy"] and row["last_seen_at"] > now - timedelta(minutes=10) for row in scopes
        )
        dag_results = []
        for entry in venue_components + auxiliary:
            rows = [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT state, start_date, end_date FROM dag_run WHERE dag_id=:dag AND run_type='scheduled' "
                        "AND state IN ('success','failed') ORDER BY end_date DESC NULLS LAST LIMIT 3"
                    ),
                    {"dag": entry["dag_id"]},
                ).mappings()
            ]
            is_venue = entry in venue_components
            required = 3 if is_venue else 1
            relevant = rows[:required]
            complete = len(relevant) == required and all(r["state"] == "success" for r in relevant)
            if is_venue:
                complete = complete and all(
                    r["start_date"] and r["start_date"] >= since for r in relevant
                )
            elif relevant:
                max_age = (
                    timedelta(days=3)
                    if entry["dag_id"] == "zacks_phone_daily_reboot"
                    else timedelta(minutes=20)
                )
                complete = complete and relevant[0]["end_date"] > now - max_age
            dag_results.append(
                {
                    "dagId": entry["dag_id"],
                    "requiredCycles": required,
                    "passed": bool(complete),
                    "recentRuns": relevant,
                }
            )
        checks["allNaturalDagCycles"] = len(venue_components) == 26 and all(
            r["passed"] for r in dag_results
        )
        paused = connection.execute(
            text("SELECT count(*) FROM dag WHERE dag_id=ANY(:ids) AND is_paused"),
            {"ids": [d["dag_id"] for d in manifest["active_dags"]]},
        ).scalar_one()
        checks["allRequiredDagsUnpaused"] = paused == 0
        queues = {}
        for table in ("notification_outbox", "system_email_outbox", "wechat_outbox"):
            groups = [
                dict(row)
                for row in connection.execute(
                    text(f"""
                SELECT status, count(*) AS count,
                    min(created_at) FILTER (WHERE status IN ('pending','retry','processing','dispatching')) AS oldest
                FROM zacks.{table} GROUP BY status ORDER BY status
            """)
                ).mappings()
            ]
            recent = [
                dict(row)
                for row in connection.execute(
                    text(f"""
                SELECT status, count(*) AS count FROM zacks.{table}
                WHERE created_at >= :since GROUP BY status ORDER BY status
            """),
                    {"since": since},
                ).mappings()
            ]
            queues[table] = {"allHistory": groups, "createdThisRelease": recent}
            unknown = sum(row["count"] for row in recent if row["status"] == "submission_unknown")
            checks[f"{table}:noNewUnknownSubmission"] = unknown == 0
            overdue = connection.execute(
                text(f"""SELECT count(*) FROM zacks.{table}
                WHERE status IN ('pending','retry','processing','dispatching')
                AND created_at < now() - interval '15 minutes'""")
            ).scalar_one()
            checks[f"{table}:noStalledBacklog"] = overdue == 0
        natural = dict(
            connection.execute(
                text("""SELECT
            (SELECT count(DISTINCT message_id) FROM zacks.notification_outbox WHERE submitted_at>=:since) AS email_submitted,
            (SELECT count(DISTINCT message_id) FROM zacks.notification_outbox WHERE submitted_at>=:since AND status='delivered') AS email_delivered,
            (SELECT count(*) FROM zacks.wechat_outbox WHERE sent_at>=:since) AS wechat_sent,
            (SELECT count(*) FROM zacks.subscriptions WHERE created_at>=:since) AS subscriptions_created
        """),
                {"since": since},
            )
            .mappings()
            .one()
        )
    sender = sender_readiness()
    checks["senderReady"] = sender.get("ok") is True
    checks["exactSenderCommit"] = sender.get("deploymentCommit") == expected_commit
    checks["senderDurableIdempotency"] = sender.get("durableIdempotency") is True
    checks["senderTransportNotCloudflareProxied"] = sender.get("cloudflareProxyObserved") is False
    if require_delivery:
        checks["naturalEmailProviderDelivered"] = natural["email_delivered"] > 0
        checks["naturalWeChatDelivered"] = natural["wechat_sent"] > 0
    return {
        "complete": True,
        "schemaVersion": 1,
        "generatedAt": now,
        "since": since,
        "deploymentCommit": expected_commit,
        "ok": all(checks.values()),
        "checks": checks,
        "failedChecks": [key for key, value in checks.items() if not value],
        "migration": {
            "sourceRevision": migration["source_revision"] if migration else None,
            "tables": proof,
        },
        "subscriptionApi": api_evidence,
        "workerHeartbeats": heartbeats,
        "venues": venues,
        "observationScopes": scopes,
        "dags": dag_results,
        "queues": queues,
        "naturalDelivery": natural,
        "sender": sender,
        "notificationsGeneratedForAcceptance": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", choices=list(COMPONENT_MAX_AGE))
    parser.add_argument("--expected-commit")
    parser.add_argument("--require-delivery", action="store_true")
    args = parser.parse_args()
    if args.worker:
        raise SystemExit(0 if worker_health(args.worker) else 1)
    if not args.expected_commit:
        parser.error("--expected-commit is required")
    report = business_report(args.expected_commit, require_delivery=args.require_delivery)
    print(
        json.dumps(
            report,
            default=lambda value: value.isoformat() if isinstance(value, datetime) else str(value),
            ensure_ascii=False,
        )
    )
    raise SystemExit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
