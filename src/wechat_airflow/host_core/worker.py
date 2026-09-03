from __future__ import annotations

import logging
import os
import socket
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text

from .database import ensure_schema, transaction
from .domain import format_digest, utc_now
from .service import runtime_heartbeat
from .settings import HostCoreSettings, load_settings, load_tencent_email_settings
from .tencent_ses import (
    TencentSesError,
    get_email_status,
    normalize_status,
    send_template_email,
)
from .weather import evaluate_weather

LOGGER = logging.getLogger("zacks.host_core.worker")
LEASE_SECONDS = 300
SUBSCRIBER_BATCH = 20
SYSTEM_BATCH = 5
RECONCILE_BATCH = 5
MAX_ATTEMPTS = 5


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _retry_at(attempt: int) -> datetime:
    seconds = min(3_600, 60 * (2 ** max(0, attempt - 1)))
    return utc_now() + timedelta(seconds=seconds)


def _shanghai_day(now: datetime) -> tuple[str, datetime]:
    from zoneinfo import ZoneInfo

    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    return local.date().isoformat(), start


def _claim_system(worker_id: str) -> dict[str, Any] | None:
    now = utc_now()
    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    with transaction() as connection:
        row = connection.execute(
            text(
                """
                SELECT id, email, email_type, subject, body, attempt_count
                FROM zacks.system_email_outbox
                WHERE status IN ('pending', 'retry', 'processing')
                  AND next_attempt_at <= :now
                  AND (lease_until IS NULL OR lease_until <= :now)
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ),
            {"now": now},
        ).mappings().first()
        if not row:
            return None
        attempt = int(row["attempt_count"] or 0) + 1
        connection.execute(
            text(
                """
                UPDATE zacks.system_email_outbox
                SET status = 'processing', attempt_count = :attempt,
                    lease_owner = :lease_owner, lease_until = :lease_until,
                    updated_at = :now
                WHERE id = :id
                """
            ),
            {
                "attempt": attempt,
                "lease_owner": worker_id,
                "lease_until": lease_until,
                "now": now,
                "id": row["id"],
            },
        )
    return {**dict(row), "attempt_count": attempt}


def _complete_system(row: Mapping[str, Any], worker_id: str) -> None:
    email_settings = load_tencent_email_settings()
    category = {
        "verification": "邮箱验证",
        "subscription_expiry": "订阅到期提醒",
    }.get(str(row["email_type"]), "系统通知")
    try:
        sent = send_template_email(
            email_settings,
            str(row["email"]),
            str(row["subject"]),
            str(row["body"]),
            category=category,
        )
        now = utc_now()
        with transaction() as connection:
            connection.execute(
                text(
                    """
                    UPDATE zacks.system_email_outbox
                    SET status = 'submitted', provider_message_id = :message_id,
                        provider_request_id = :request_id, provider_status = 'accepted',
                        submitted_at = :now, provider_checked_at = NULL,
                        lease_owner = NULL, lease_until = NULL,
                        last_error = NULL, updated_at = :now
                    WHERE id = :id AND lease_owner = :lease_owner
                    """
                ),
                {
                    "message_id": sent.message_id,
                    "request_id": sent.request_id,
                    "now": now,
                    "id": row["id"],
                    "lease_owner": worker_id,
                },
            )
    except Exception as exc:
        attempt = int(row["attempt_count"])
        status = "failed" if attempt >= MAX_ATTEMPTS else "retry"
        now = utc_now()
        with transaction() as connection:
            connection.execute(
                text(
                    """
                    UPDATE zacks.system_email_outbox
                    SET status = :status, next_attempt_at = :next_attempt_at,
                        failed_at = CASE WHEN :status = 'failed' THEN :now ELSE failed_at END,
                        lease_owner = NULL, lease_until = NULL,
                        last_error = :last_error, updated_at = :now
                    WHERE id = :id AND lease_owner = :lease_owner
                    """
                ),
                {
                    "status": status,
                    "next_attempt_at": _retry_at(attempt),
                    "now": now,
                    "last_error": str(exc)[:500],
                    "id": row["id"],
                    "lease_owner": worker_id,
                },
            )
        LOGGER.warning("system email attempt failed", extra={"email_type": row["email_type"]})


def _claim_subscriber_group(
    worker_id: str,
    settings: HostCoreSettings,
) -> list[dict[str, Any]]:
    now = utc_now()
    delivery_day, day_start = _shanghai_day(now)
    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    with transaction() as connection:
        first = connection.execute(
            text(
                """
                SELECT email, tier
                FROM zacks.notification_outbox
                WHERE status IN ('pending', 'retry', 'processing')
                  AND next_attempt_at <= :now
                  AND (lease_until IS NULL OR lease_until <= :now)
                ORDER BY CASE WHEN tier = 'priority' THEN 0 ELSE 1 END, created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ),
            {"now": now},
        ).mappings().first()
        if not first:
            return []

        rows = [
            dict(row)
            for row in connection.execute(
                text(
                    """
                    SELECT id, email, subject, body, venue_id, tier, attempt_count
                    FROM zacks.notification_outbox
                    WHERE email = :email
                      AND status IN ('pending', 'retry', 'processing')
                      AND next_attempt_at <= :now
                      AND (lease_until IS NULL OR lease_until <= :now)
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT :batch
                    """
                ),
                {"email": first["email"], "now": now, "batch": SUBSCRIBER_BATCH},
            ).mappings()
        ]
        if not rows:
            return []

        tier = "priority" if first["tier"] == "priority" else "standard"
        weather = evaluate_weather(settings)
        if tier == "standard" and not weather.send_email:
            connection.execute(
                text(
                    """
                    UPDATE zacks.notification_outbox
                    SET status = 'suppressed', last_error = :reason,
                        lease_owner = NULL, lease_until = NULL, updated_at = :now
                    WHERE id = ANY(:ids)
                    """
                ),
                {
                    "reason": (
                        f"weather_suppressed:{weather.forecast_date}:"
                        f"{weather.precipitation_mm}mm:threshold={weather.threshold_mm}mm"
                    ),
                    "now": now,
                    "ids": [row["id"] for row in rows],
                },
            )
            return []

        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"zacks-email:{first['email']}:{delivery_day}"},
        )
        user_limit = (
            settings.priority_daily_email_limit
            if tier == "priority"
            else settings.standard_daily_email_limit
        )
        user_submitted = int(
            connection.execute(
                text(
                    """
                    SELECT count(DISTINCT message_id)
                    FROM zacks.notification_outbox
                    WHERE email = :email AND submitted_at >= :day_start
                    """
                ),
                {"email": first["email"], "day_start": day_start},
            ).scalar_one()
        )
        global_submitted = int(
            connection.execute(
                text(
                    """
                    SELECT count(DISTINCT message_id)
                    FROM zacks.notification_outbox
                    WHERE submitted_at >= :day_start
                    """
                ),
                {"day_start": day_start},
            ).scalar_one()
        )
        if user_submitted >= user_limit or global_submitted >= settings.notification_daily_send_limit:
            reason = (
                f"daily_tier_limit:{delivery_day}:tier={tier}:limit={user_limit}"
                if user_submitted >= user_limit
                else f"global_daily_limit:{delivery_day}:limit={settings.notification_daily_send_limit}"
            )
            connection.execute(
                text(
                    """
                    UPDATE zacks.notification_outbox
                    SET status = 'suppressed', last_error = :reason,
                        lease_owner = NULL, lease_until = NULL, updated_at = :now
                    WHERE id = ANY(:ids)
                    """
                ),
                {"reason": reason, "now": now, "ids": [row["id"] for row in rows]},
            )
            return []

        for row in rows:
            row["attempt_count"] = int(row["attempt_count"] or 0) + 1
        connection.execute(
            text(
                """
                UPDATE zacks.notification_outbox
                SET status = 'processing', attempt_count = attempt_count + 1,
                    lease_owner = :lease_owner, lease_until = :lease_until,
                    updated_at = :now
                WHERE id = ANY(:ids)
                """
            ),
            {
                "lease_owner": worker_id,
                "lease_until": lease_until,
                "now": now,
                "ids": [row["id"] for row in rows],
            },
        )
        claim_id = str(uuid.uuid4())
        connection.execute(
            text(
                """
                INSERT INTO zacks.email_delivery_claims(
                    id, email, delivery_day, status, created_at, updated_at
                ) VALUES (:id, :email, CAST(:delivery_day AS date), 'reserved', :now, :now)
                """
            ),
            {
                "id": claim_id,
                "email": first["email"],
                "delivery_day": delivery_day,
                "now": now,
            },
        )
        for row in rows:
            row["claim_id"] = claim_id
    return rows


def _complete_subscriber(rows: list[dict[str, Any]], worker_id: str) -> None:
    if not rows:
        return
    email_settings = load_tencent_email_settings()
    subject, body = format_digest(str(row["body"]) for row in rows)
    try:
        sent = send_template_email(
            email_settings,
            str(rows[0]["email"]),
            subject,
            body,
            category="网球空场提醒",
        )
        now = utc_now()
        message_id = sent.message_id or f"host:{uuid.uuid4()}"
        with transaction() as connection:
            connection.execute(
                text(
                    """
                    UPDATE zacks.notification_outbox
                    SET status = 'submitted', message_id = :message_id,
                        provider_request_id = :request_id, provider_status = 'accepted',
                        submitted_at = :now, provider_checked_at = NULL,
                        provider_error = NULL, last_error = NULL,
                        lease_owner = NULL, lease_until = NULL, updated_at = :now
                    WHERE id = ANY(:ids) AND lease_owner = :lease_owner
                    """
                ),
                {
                    "message_id": message_id,
                    "request_id": sent.request_id,
                    "now": now,
                    "ids": [row["id"] for row in rows],
                    "lease_owner": worker_id,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE zacks.email_delivery_claims
                    SET status = 'sent', message_id = :message_id, updated_at = :now
                    WHERE id = :id AND status = 'reserved'
                    """
                ),
                {
                    "message_id": message_id,
                    "now": now,
                    "id": rows[0]["claim_id"],
                },
            )
    except Exception as exc:
        now = utc_now()
        terminal = all(int(row["attempt_count"]) >= MAX_ATTEMPTS for row in rows)
        status = "failed" if terminal else "retry"
        next_attempt_at = _retry_at(max(int(row["attempt_count"]) for row in rows))
        with transaction() as connection:
            connection.execute(
                text(
                    """
                    UPDATE zacks.notification_outbox
                    SET status = :status, next_attempt_at = :next_attempt_at,
                        failed_at = CASE WHEN :status = 'failed' THEN :now ELSE failed_at END,
                        lease_owner = NULL, lease_until = NULL,
                        last_error = :reason, updated_at = :now
                    WHERE id = ANY(:ids) AND lease_owner = :lease_owner
                    """
                ),
                {
                    "status": status,
                    "next_attempt_at": next_attempt_at,
                    "now": now,
                    "reason": str(exc)[:500],
                    "ids": [row["id"] for row in rows],
                    "lease_owner": worker_id,
                },
            )
            connection.execute(
                text(
                    """
                    UPDATE zacks.email_delivery_claims
                    SET status = 'released', updated_at = :now
                    WHERE id = :id AND status = 'reserved'
                    """
                ),
                {"now": now, "id": rows[0]["claim_id"]},
            )
        LOGGER.warning("subscriber email attempt failed", extra={"tier": rows[0]["tier"]})


def _reconcile_subscriber(settings: HostCoreSettings) -> int:
    email_settings = load_tencent_email_settings()
    now = utc_now()
    due_before = now - timedelta(minutes=5)
    with transaction() as connection:
        rows = connection.execute(
            text(
                """
                SELECT message_id, min(email) AS email
                FROM zacks.notification_outbox
                WHERE status = 'submitted'
                  AND message_id IS NOT NULL
                  AND (provider_checked_at IS NULL OR provider_checked_at <= :due_before)
                GROUP BY message_id
                ORDER BY min(submitted_at)
                LIMIT :batch
                """
            ),
            {"due_before": due_before, "batch": RECONCILE_BATCH},
        ).mappings().all()
    reconciled = 0
    for row in rows:
        try:
            provider = get_email_status(email_settings, row["message_id"], row["email"])
            status, reason, delivered_at = normalize_status(provider)
            checked_at = utc_now()
            with transaction() as connection:
                if status == "delivered":
                    venue_ids = [
                        value
                        for value in connection.execute(
                            text(
                                """
                                SELECT DISTINCT venue_id FROM zacks.notification_outbox
                                WHERE message_id = :message_id
                                """
                            ),
                            {"message_id": row["message_id"]},
                        ).scalars()
                    ]
                    connection.execute(
                        text(
                            """
                            UPDATE zacks.notification_outbox
                            SET status = 'delivered', delivered_at = :delivered_at,
                                provider_status = 'delivered', provider_checked_at = :checked_at,
                                provider_error = NULL, updated_at = :checked_at
                            WHERE message_id = :message_id AND status = 'submitted'
                            """
                        ),
                        {
                            "delivered_at": delivered_at or checked_at,
                            "checked_at": checked_at,
                            "message_id": row["message_id"],
                        },
                    )
                    connection.execute(
                        text(
                            """
                            UPDATE zacks.venue_status
                            SET last_notification_at = :delivered_at, updated_at = :checked_at
                            WHERE venue_id = ANY(:venue_ids)
                            """
                        ),
                        {
                            "delivered_at": delivered_at or checked_at,
                            "checked_at": checked_at,
                            "venue_ids": venue_ids,
                        },
                    )
                elif status == "failed":
                    connection.execute(
                        text(
                            """
                            UPDATE zacks.notification_outbox
                            SET status = 'failed', failed_at = :checked_at,
                                provider_status = 'failed', provider_checked_at = :checked_at,
                                provider_error = :reason, last_error = :reason,
                                updated_at = :checked_at
                            WHERE message_id = :message_id AND status = 'submitted'
                            """
                        ),
                        {
                            "checked_at": checked_at,
                            "reason": reason,
                            "message_id": row["message_id"],
                        },
                    )
                else:
                    connection.execute(
                        text(
                            """
                            UPDATE zacks.notification_outbox
                            SET provider_status = 'pending', provider_checked_at = :checked_at,
                                provider_error = :reason, updated_at = :checked_at
                            WHERE message_id = :message_id AND status = 'submitted'
                            """
                        ),
                        {
                            "checked_at": checked_at,
                            "reason": reason,
                            "message_id": row["message_id"],
                        },
                    )
            reconciled += 1
        except Exception as exc:
            LOGGER.warning("delivery reconciliation failed", extra={"error": type(exc).__name__})
    return reconciled


def _maintenance() -> None:
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            text(
                """
                UPDATE zacks.subscriptions subscriptions
                SET active_until = :renewed_until, updated_at = :now
                WHERE active = true
                  AND auto_renew = true
                  AND active_until <= :threshold
                  AND EXISTS (
                      SELECT 1 FROM zacks.user_delivery_tiers tiers
                      WHERE tiers.email = subscriptions.email
                        AND tiers.tier = 'priority' AND tiers.revoked_at IS NULL
                  )
                """
            ),
            {
                "renewed_until": now + timedelta(days=90),
                "threshold": now + timedelta(days=45),
                "now": now,
            },
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.system_email_outbox(
                    id, dedupe_key, email, email_type, subject, body, status,
                    attempt_count, next_attempt_at, created_at, updated_at
                )
                SELECT
                    md5(random()::text || clock_timestamp()::text || subscriptions.id),
                    'subscription-expiry:' || subscriptions.id,
                    subscriptions.email,
                    'subscription_expiry',
                    '网球提醒订阅将在1天内到期',
                    '你的网球提醒订阅将在 ' || to_char(subscriptions.active_until, 'YYYY-MM-DD HH24:MI')
                      || ' 到期。请登录 Zacks 网球提醒续订或创建新的订阅。',
                    'pending', 0, :now, :now, :now
                FROM zacks.subscriptions subscriptions
                WHERE subscriptions.active = true
                  AND subscriptions.auto_renew = false
                  AND subscriptions.active_until > :now
                  AND subscriptions.active_until <= :tomorrow
                ON CONFLICT (dedupe_key) DO NOTHING
                """
            ),
            {"now": now, "tomorrow": now + timedelta(days=1)},
        )
        connection.execute(
            text(
                """
                DELETE FROM zacks.verification_challenges
                WHERE created_at < :challenge_cutoff
                """
            ),
            {"challenge_cutoff": now - timedelta(days=2)},
        )
        connection.execute(
            text(
                """
                DELETE FROM zacks.observed_slots
                WHERE last_observed_at < :slot_cutoff
                """
            ),
            {"slot_cutoff": now - timedelta(days=45)},
        )
        connection.execute(
            text(
                """
                DELETE FROM zacks.wechat_delivery_incidents
                WHERE resolved_at IS NOT NULL AND resolved_at < :incident_cutoff
                """
            ),
            {"incident_cutoff": now - timedelta(days=90)},
        )


def run_cycle(worker_id: str, settings: HostCoreSettings) -> dict[str, int]:
    sent_system = 0
    sent_subscriber = 0
    for _ in range(SYSTEM_BATCH):
        row = _claim_system(worker_id)
        if not row:
            break
        _complete_system(row, worker_id)
        sent_system += 1
    for _ in range(SUBSCRIBER_BATCH):
        rows = _claim_subscriber_group(worker_id, settings)
        if not rows:
            break
        _complete_subscriber(rows, worker_id)
        sent_subscriber += 1
    reconciled = _reconcile_subscriber(settings)
    return {
        "system": sent_system,
        "subscriber": sent_subscriber,
        "reconciled": reconciled,
    }


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("ZACKS_WORKER_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    ensure_schema()
    worker_id = _worker_id()
    last_maintenance = 0.0
    while True:
        settings = load_settings()
        try:
            if settings.host_owns_delivery:
                counts = run_cycle(worker_id, settings)
                if time.monotonic() - last_maintenance >= 3_600:
                    _maintenance()
                    last_maintenance = time.monotonic()
                runtime_heartbeat(
                    "zacks-notification-worker",
                    settings.deployment_commit,
                    {"owner": True, **counts},
                )
                time.sleep(2 if any(counts.values()) else 5)
            else:
                runtime_heartbeat(
                    "zacks-notification-worker",
                    settings.deployment_commit,
                    {"owner": False, "mode": "shadow"},
                )
                time.sleep(15)
        except KeyboardInterrupt:
            return
        except Exception as exc:
            LOGGER.exception("notification worker cycle failed", extra={"error": type(exc).__name__})
            time.sleep(10)


if __name__ == "__main__":
    main()
