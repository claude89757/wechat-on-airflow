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
from .tencent_ses import get_email_status, normalize_status, send_template_email
from .weather import WeatherDecision, evaluate_weather

LOGGER = logging.getLogger("zacks.host_core.worker")
LEASE_SECONDS = 300
SUBSCRIBER_ROWS_PER_DIGEST = 20
SYSTEM_BATCH = 5
RECONCILE_BATCH = 5
MAX_ATTEMPTS = 5
PROVIDER_RETENTION_DAYS = 30


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _retry_at(attempt: int) -> datetime:
    seconds = min(3_600, 60 * (2 ** max(0, attempt - 1)))
    return utc_now() + timedelta(seconds=seconds)


def _provider_backoff(check_count: int) -> timedelta:
    if check_count <= 2:
        return timedelta(minutes=5)
    if check_count <= 5:
        return timedelta(minutes=15)
    if check_count <= 8:
        return timedelta(hours=1)
    return timedelta(hours=6)


def _shanghai_day(now: datetime) -> tuple[str, datetime]:
    from zoneinfo import ZoneInfo

    local = now.astimezone(ZoneInfo("Asia/Shanghai"))
    start = local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    return local.date().isoformat(), start


def _release_expired_leases() -> None:
    now = utc_now()
    with transaction() as connection:
        connection.execute(
            text(
                """
                UPDATE zacks.notification_outbox
                SET status = 'retry', lease_owner = NULL, lease_until = NULL,
                    next_attempt_at = :now, updated_at = :now,
                    last_error = COALESCE(last_error, 'expired processing lease')
                WHERE status = 'processing' AND lease_until <= :now
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                UPDATE zacks.system_email_outbox
                SET status = 'retry', lease_owner = NULL, lease_until = NULL,
                    next_attempt_at = :now, updated_at = :now,
                    last_error = COALESCE(last_error, 'expired processing lease')
                WHERE status = 'processing' AND lease_until <= :now
                """
            ),
            {"now": now},
        )
        connection.execute(
            text(
                """
                UPDATE zacks.email_delivery_claims
                SET status = 'released', updated_at = :now
                WHERE status = 'reserved' AND updated_at <= :cutoff
                """
            ),
            {"now": now, "cutoff": now - timedelta(seconds=LEASE_SECONDS)},
        )


def _claim_system(worker_id: str) -> dict[str, Any] | None:
    now = utc_now()
    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    with transaction() as connection:
        row = (
            connection.execute(
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
            )
            .mappings()
            .first()
        )
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
                        provider_check_count = 0,
                        provider_next_check_at = :next_check,
                        lease_owner = NULL, lease_until = NULL,
                        last_error = NULL, updated_at = :now
                    WHERE id = :id AND lease_owner = :lease_owner
                    """
                ),
                {
                    "message_id": sent.message_id,
                    "request_id": sent.request_id,
                    "now": now,
                    "next_check": now + timedelta(minutes=5),
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
        LOGGER.warning(
            "system email attempt failed",
            extra={"email_type": row["email_type"], "error": type(exc).__name__},
        )


def _next_subscriber_target() -> dict[str, str] | None:
    now = utc_now()
    with transaction() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT email, tier
                FROM zacks.notification_outbox
                WHERE status IN ('pending', 'retry', 'processing')
                  AND next_attempt_at <= :now
                  AND (lease_until IS NULL OR lease_until <= :now)
                ORDER BY CASE WHEN tier = 'priority' THEN 0 ELSE 1 END, created_at
                LIMIT 1
                """
                ),
                {"now": now},
            )
            .mappings()
            .first()
        )
    if not row:
        return None
    return {"email": str(row["email"]), "tier": str(row["tier"])}


def _claim_subscriber_group(
    worker_id: str,
    settings: HostCoreSettings,
    target: Mapping[str, str],
    weather: WeatherDecision,
) -> list[dict[str, Any]]:
    now = utc_now()
    delivery_day, day_start = _shanghai_day(now)
    lease_until = now + timedelta(seconds=LEASE_SECONDS)
    with transaction() as connection:
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
                {
                    "email": target["email"],
                    "now": now,
                    "batch": SUBSCRIBER_ROWS_PER_DIGEST,
                },
            ).mappings()
        ]
        if not rows:
            return []

        tier = "priority" if target["tier"] == "priority" else "standard"
        ids = [row["id"] for row in rows]
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
                    "ids": ids,
                },
            )
            return []

        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"zacks-global-email:{delivery_day}"},
        )
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": f"zacks-user-email:{target['email']}:{delivery_day}"},
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
                {"email": target["email"], "day_start": day_start},
            ).scalar_one()
        )
        user_reserved = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM zacks.email_delivery_claims
                    WHERE email = :email
                      AND delivery_day = CAST(:delivery_day AS date)
                      AND status = 'reserved'
                      AND updated_at > :reservation_cutoff
                    """
                ),
                {
                    "email": target["email"],
                    "delivery_day": delivery_day,
                    "reservation_cutoff": now - timedelta(seconds=LEASE_SECONDS),
                },
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
        global_reserved = int(
            connection.execute(
                text(
                    """
                    SELECT count(*) FROM zacks.email_delivery_claims
                    WHERE delivery_day = CAST(:delivery_day AS date)
                      AND status = 'reserved'
                      AND updated_at > :reservation_cutoff
                    """
                ),
                {
                    "delivery_day": delivery_day,
                    "reservation_cutoff": now - timedelta(seconds=LEASE_SECONDS),
                },
            ).scalar_one()
        )
        if (
            user_submitted + user_reserved >= user_limit
            or global_submitted + global_reserved >= settings.notification_daily_send_limit
        ):
            reason = (
                f"daily_tier_limit:{delivery_day}:tier={tier}:limit={user_limit}"
                if user_submitted + user_reserved >= user_limit
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
                {"reason": reason, "now": now, "ids": ids},
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
                "ids": ids,
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
                "email": target["email"],
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
                        provider_check_count = 0,
                        provider_next_check_at = :next_check,
                        provider_error = NULL, last_error = NULL,
                        lease_owner = NULL, lease_until = NULL, updated_at = :now
                    WHERE id = ANY(:ids) AND lease_owner = :lease_owner
                    """
                ),
                {
                    "message_id": message_id,
                    "request_id": sent.request_id,
                    "now": now,
                    "next_check": now + timedelta(minutes=5),
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
        LOGGER.warning(
            "subscriber email attempt failed",
            extra={"tier": rows[0]["tier"], "error": type(exc).__name__},
        )


def _next_provider_check(
    table: str,
    message_column: str,
    email_column: str,
) -> dict[str, Any] | None:
    now = utc_now()
    retention_cutoff = now - timedelta(days=PROVIDER_RETENTION_DAYS)
    with transaction() as connection:
        row = (
            connection.execute(
                text(
                    f"""
                SELECT {message_column} AS message_id,
                       min({email_column}) AS email,
                       min(submitted_at) AS submitted_at,
                       max(provider_check_count) AS provider_check_count
                FROM zacks.{table}
                WHERE status = 'submitted'
                  AND {message_column} IS NOT NULL
                  AND submitted_at >= :retention_cutoff
                  AND provider_next_check_at <= :now
                GROUP BY {message_column}
                ORDER BY min(provider_next_check_at), min(submitted_at)
                LIMIT 1
                """
                ),
                {"retention_cutoff": retention_cutoff, "now": now},
            )
            .mappings()
            .first()
        )
    return dict(row) if row else None


def _update_provider_pending(
    table: str,
    message_column: str,
    message_id: str,
    check_count: int,
    reason: str | None,
) -> None:
    now = utc_now()
    next_count = check_count + 1
    with transaction() as connection:
        connection.execute(
            text(
                f"""
                UPDATE zacks.{table}
                SET provider_status = 'pending', provider_checked_at = :now,
                    provider_check_count = :check_count,
                    provider_next_check_at = :next_check,
                    provider_error = :reason,
                    updated_at = :now
                WHERE {message_column} = :message_id AND status = 'submitted'
                """
            ),
            {
                "now": now,
                "check_count": next_count,
                "next_check": now + _provider_backoff(next_count),
                "reason": reason,
                "message_id": message_id,
            },
        )


def _reconcile_subscriber_row(settings: HostCoreSettings, row: Mapping[str, Any]) -> None:
    email_settings = load_tencent_email_settings()
    message_id = str(row["message_id"])
    checked_at = utc_now()
    try:
        provider = get_email_status(email_settings, message_id, str(row["email"]))
        status, reason, delivered_at = normalize_status(provider)
    except Exception as exc:
        _update_provider_pending(
            "notification_outbox",
            "message_id",
            message_id,
            int(row["provider_check_count"] or 0),
            str(exc)[:500],
        )
        return

    if status == "pending":
        _update_provider_pending(
            "notification_outbox",
            "message_id",
            message_id,
            int(row["provider_check_count"] or 0),
            reason,
        )
        return

    with transaction() as connection:
        if status == "delivered":
            venue_ids = list(
                connection.execute(
                    text(
                        """
                        SELECT DISTINCT venue_id FROM zacks.notification_outbox
                        WHERE message_id = :message_id
                        """
                    ),
                    {"message_id": message_id},
                ).scalars()
            )
            connection.execute(
                text(
                    """
                    UPDATE zacks.notification_outbox
                    SET status = 'delivered', delivered_at = :delivered_at,
                        provider_status = 'delivered', provider_checked_at = :checked_at,
                        provider_next_check_at = NULL, provider_error = NULL,
                        updated_at = :checked_at
                    WHERE message_id = :message_id AND status = 'submitted'
                    """
                ),
                {
                    "delivered_at": delivered_at or checked_at,
                    "checked_at": checked_at,
                    "message_id": message_id,
                },
            )
            if venue_ids:
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
        else:
            connection.execute(
                text(
                    """
                    UPDATE zacks.notification_outbox
                    SET status = 'failed', failed_at = :checked_at,
                        provider_status = 'failed', provider_checked_at = :checked_at,
                        provider_next_check_at = NULL,
                        provider_error = :reason, last_error = :reason,
                        updated_at = :checked_at
                    WHERE message_id = :message_id AND status = 'submitted'
                    """
                ),
                {
                    "checked_at": checked_at,
                    "reason": reason or "provider delivery failed",
                    "message_id": message_id,
                },
            )


def _reconcile_system_row(row: Mapping[str, Any]) -> None:
    email_settings = load_tencent_email_settings()
    message_id = str(row["message_id"])
    checked_at = utc_now()
    try:
        provider = get_email_status(email_settings, message_id, str(row["email"]))
        status, reason, delivered_at = normalize_status(provider)
    except Exception as exc:
        _update_provider_pending(
            "system_email_outbox",
            "provider_message_id",
            message_id,
            int(row["provider_check_count"] or 0),
            str(exc)[:500],
        )
        return

    if status == "pending":
        _update_provider_pending(
            "system_email_outbox",
            "provider_message_id",
            message_id,
            int(row["provider_check_count"] or 0),
            reason,
        )
        return

    with transaction() as connection:
        if status == "delivered":
            connection.execute(
                text(
                    """
                    UPDATE zacks.system_email_outbox
                    SET status = 'delivered', delivered_at = :delivered_at,
                        provider_status = 'delivered', provider_checked_at = :checked_at,
                        provider_next_check_at = NULL, last_error = NULL,
                        updated_at = :checked_at
                    WHERE provider_message_id = :message_id AND status = 'submitted'
                    """
                ),
                {
                    "delivered_at": delivered_at or checked_at,
                    "checked_at": checked_at,
                    "message_id": message_id,
                },
            )
        else:
            connection.execute(
                text(
                    """
                    UPDATE zacks.system_email_outbox
                    SET status = 'failed', failed_at = :checked_at,
                        provider_status = 'failed', provider_checked_at = :checked_at,
                        provider_next_check_at = NULL,
                        last_error = :reason, updated_at = :checked_at
                    WHERE provider_message_id = :message_id AND status = 'submitted'
                    """
                ),
                {
                    "checked_at": checked_at,
                    "reason": reason or "provider delivery failed",
                    "message_id": message_id,
                },
            )


def _reconcile(settings: HostCoreSettings) -> int:
    processed = 0
    for _ in range(RECONCILE_BATCH):
        subscriber = _next_provider_check("notification_outbox", "message_id", "email")
        if not subscriber:
            break
        _reconcile_subscriber_row(settings, subscriber)
        processed += 1
    for _ in range(RECONCILE_BATCH):
        system = _next_provider_check("system_email_outbox", "provider_message_id", "email")
        if not system:
            break
        _reconcile_system_row(system)
        processed += 1
    return processed


def _maintenance() -> None:
    now = utc_now()
    retention_cutoff = now - timedelta(days=PROVIDER_RETENTION_DAYS)
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
                UPDATE zacks.notification_outbox
                SET status = 'failed', failed_at = :now,
                    provider_status = 'status_check_expired',
                    provider_next_check_at = NULL,
                    provider_error = 'provider status retention window elapsed',
                    last_error = 'provider status retention window elapsed',
                    updated_at = :now
                WHERE status = 'submitted' AND submitted_at < :retention_cutoff
                """
            ),
            {"now": now, "retention_cutoff": retention_cutoff},
        )
        connection.execute(
            text(
                """
                UPDATE zacks.system_email_outbox
                SET status = 'failed', failed_at = :now,
                    provider_status = 'status_check_expired',
                    provider_next_check_at = NULL,
                    last_error = 'provider status retention window elapsed',
                    updated_at = :now
                WHERE status = 'submitted' AND submitted_at < :retention_cutoff
                """
            ),
            {"now": now, "retention_cutoff": retention_cutoff},
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

    for _ in range(SUBSCRIBER_ROWS_PER_DIGEST):
        target = _next_subscriber_target()
        if not target:
            break
        weather = evaluate_weather(settings)
        rows = _claim_subscriber_group(worker_id, settings, target, weather)
        if not rows:
            continue
        _complete_subscriber(rows, worker_id)
        sent_subscriber += 1

    reconciled = _reconcile(settings)
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
    last_lease_recovery = 0.0
    last_heartbeat = 0.0
    latest_counts: dict[str, int] = {"system": 0, "subscriber": 0, "reconciled": 0}

    while True:
        settings = load_settings()
        try:
            monotonic = time.monotonic()
            if monotonic - last_lease_recovery >= 60:
                _release_expired_leases()
                last_lease_recovery = monotonic

            if settings.host_owns_delivery:
                latest_counts = run_cycle(worker_id, settings)
                if monotonic - last_maintenance >= 3_600:
                    _maintenance()
                    last_maintenance = monotonic
                sleep_seconds = 2 if any(latest_counts.values()) else 5
            else:
                latest_counts = {"system": 0, "subscriber": 0, "reconciled": 0}
                sleep_seconds = 15

            if monotonic - last_heartbeat >= 60:
                runtime_heartbeat(
                    "zacks-notification-worker",
                    settings.deployment_commit,
                    {
                        "owner": settings.host_owns_delivery,
                        "mode": "active" if settings.host_owns_delivery else "shadow",
                        **latest_counts,
                    },
                )
                last_heartbeat = monotonic
            time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            return
        except Exception as exc:
            LOGGER.exception(
                "notification worker cycle failed",
                extra={"error": type(exc).__name__},
            )
            time.sleep(10)


if __name__ == "__main__":
    main()
