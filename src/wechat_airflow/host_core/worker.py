from __future__ import annotations

import json
import logging
import os
import socket
import time
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

import requests
from sqlalchemy import text

from .control import delivery_guard
from .database import ensure_schema, transaction
from .domain import format_digest, utc_now
from .service import runtime_heartbeat
from .settings import HostCoreSettings, load_settings, load_tencent_email_settings
from .tencent_ses import TencentSesError, get_email_status, normalize_status, send_template_email
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
        for table in ("notification_outbox", "system_email_outbox"):
            connection.execute(
                text(f"""
                UPDATE zacks.{table} SET status = 'submission_unknown', updated_at = :now,
                    last_error = 'dispatch interrupted; reconcile before replay',
                    lease_owner = NULL, lease_until = NULL
                WHERE status = 'dispatching' AND lease_until <= :now
            """),
                {"now": now},
            )
        connection.execute(
            text("""
            UPDATE zacks.email_delivery_claims c SET status = 'unknown', updated_at = :now
            WHERE status = 'reserved' AND EXISTS (SELECT 1 FROM zacks.notification_outbox o
                WHERE o.delivery_claim_id = c.id AND o.status = 'submission_unknown')
        """),
            {"now": now},
        )
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


def _retryable_send_error(exc: Exception) -> bool:
    if isinstance(exc, requests.ConnectTimeout):
        return True
    # Only an explicit pre-submission provider rejection is safe to retry.
    return isinstance(exc, TencentSesError) and exc.code.split(".")[0] in {
        "AuthFailure",
        "InvalidParameter",
        "InvalidParameterValue",
        "MissingParameter",
        "LimitExceeded",
        "RequestLimitExceeded",
        "UnauthorizedOperation",
        "UnsupportedOperation",
        "ResourceNotFound",
        "ResourceUnavailable",
    }


def _attempt_email(rows: list[dict[str, Any]], worker: str, *, system: bool) -> None:
    table = "system_email_outbox" if system else "notification_outbox"
    now = utc_now()
    # Configuration failures occur before the irreversible dispatch phase.
    settings = load_tencent_email_settings()
    with delivery_guard() as enabled:
        if not enabled:
            return  # Prepared claim expires safely; no external call was made.
        with transaction() as connection:
            ids = [row["id"] for row in rows]
            if system:
                valid_ids = set(
                    connection.execute(
                        text("""
                    SELECT id FROM zacks.system_email_outbox
                    WHERE id = ANY(:ids) AND status = 'processing' AND lease_owner = :worker
                      AND (COALESCE(expires_at, CASE WHEN email_type = 'verification'
                          THEN created_at + interval '10 minutes' ELSE created_at + interval '1 day' END) > :now)
                """),
                        {"ids": ids, "worker": worker, "now": now},
                    ).scalars()
                )
            else:
                valid_ids = set(
                    connection.execute(
                        text("""
                    SELECT o.id FROM zacks.notification_outbox o
                    JOIN zacks.subscriptions s ON s.id = o.subscription_id
                    JOIN zacks.observed_slots slot ON slot.event_key = o.event_key
                    LEFT JOIN zacks.user_delivery_tiers tier ON tier.email = s.email
                    WHERE o.id = ANY(:ids) AND o.status = 'processing' AND o.lease_owner = :worker
                      AND s.active AND s.active_until > :now
                      AND (NOT s.auto_renew OR (tier.tier = 'priority' AND tier.revoked_at IS NULL))
                      AND o.created_at > :now - interval '15 minutes'
                      AND (slot.booking_date + CAST(slot.start_time AS time)) AT TIME ZONE 'Asia/Shanghai' > :now
                      AND EXISTS(SELECT 1 FROM zacks.current_availability c
                          WHERE c.event_key = o.event_key AND c.last_seen_at > :now - interval '15 minutes')
                """),
                        {"ids": ids, "worker": worker, "now": now},
                    ).scalars()
                )
            invalid = list(set(ids) - valid_ids)
            if invalid:
                connection.execute(
                    text(f"""
                    UPDATE zacks.{table} SET status = 'expired', last_error = 'not_eligible_at_dispatch',
                        lease_owner = NULL, lease_until = NULL, updated_at = :now
                    WHERE id = ANY(:ids) AND lease_owner = :worker
                """),
                    {"ids": invalid, "worker": worker, "now": now},
                )
            if not valid_ids:
                if not system and rows:
                    connection.execute(
                        text(
                            "UPDATE zacks.email_delivery_claims SET status = 'released', updated_at = now() WHERE id = :id"
                        ),
                        {"id": rows[0]["claim_id"]},
                    )
                return
            rows = [r for r in rows if r["id"] in valid_ids]
            ids = [r["id"] for r in rows]
            attempt_id = str(uuid.uuid4())
            connection.execute(
                text("""
                INSERT INTO zacks.delivery_attempts(id, channel, queue_ids, phase)
                VALUES (:id, :channel, CAST(:ids AS jsonb), 'dispatching')
            """),
                {
                    "id": attempt_id,
                    "channel": "system_email" if system else "subscriber_email",
                    "ids": json.dumps(ids),
                },
            )
            connection.execute(
                text(f"""
                UPDATE zacks.{table} SET status = 'dispatching', updated_at = :now
                WHERE id = ANY(:ids) AND lease_owner = :worker
            """),
                {"ids": ids, "worker": worker, "now": now},
            )
        if system:
            subject, body = str(rows[0]["subject"]), str(rows[0]["body"])
            category = "邮箱验证" if rows[0]["email_type"] == "verification" else "系统通知"
        else:
            subject, body = format_digest(str(row["body"]) for row in rows)
            category = "网球空场提醒"
        phase, reason, sent = "submission_unknown", None, None
        try:
            sent = send_template_email(
                settings, str(rows[0]["email"]), subject, body, category=category
            )
            if not sent.message_id:
                reason = "provider_acknowledgement_missing_message_id"
            else:
                phase = "submitted"
        except Exception as exc:
            reason = exc.code if isinstance(exc, TencentSesError) else type(exc).__name__
            if _retryable_send_error(exc):
                phase = (
                    "failed"
                    if max(int(r["attempt_count"]) for r in rows) >= MAX_ATTEMPTS
                    else "retry"
                )
        # A DB exception after external acceptance escapes; the dispatch lease will
        # become submission_unknown, never an automatic second delivery.
        with transaction() as connection:
            connection.execute(
                text("""
                UPDATE zacks.delivery_attempts SET phase = :phase, provider_message_id = :message,
                    error_code = :reason, finished_at = now() WHERE id = :id
            """),
                {
                    "phase": phase,
                    "message": sent.message_id if sent else None,
                    "reason": reason,
                    "id": attempt_id,
                },
            )
            message_column = "provider_message_id" if system else "message_id"
            connection.execute(
                text(f"""
                UPDATE zacks.{table} SET status = :phase, {message_column} = :message,
                    provider_request_id = :request, provider_status = :provider_status,
                    submitted_at = CASE WHEN :phase = 'submitted' THEN now() ELSE submitted_at END,
                    failed_at = CASE WHEN :phase = 'failed' THEN now() ELSE failed_at END,
                    provider_check_count = 0,
                    provider_next_check_at = CASE WHEN :phase = 'submitted' THEN now() + interval '30 seconds' ELSE NULL END,
                    next_attempt_at = :retry_at, lease_owner = NULL, lease_until = NULL,
                    last_error = :reason, updated_at = now()
                WHERE id = ANY(:ids) AND lease_owner = :worker AND status = 'dispatching'
            """),
                {
                    "phase": phase,
                    "message": sent.message_id if sent else None,
                    "request": sent.request_id if sent else None,
                    "provider_status": "accepted" if phase == "submitted" else phase,
                    "retry_at": _retry_at(max(int(r["attempt_count"]) for r in rows)),
                    "reason": reason,
                    "ids": ids,
                    "worker": worker,
                },
            )
            if not system:
                connection.execute(
                    text("""
                    UPDATE zacks.email_delivery_claims SET status = :status,
                        message_id = :message, updated_at = now() WHERE id = :id
                """),
                    {
                        "status": "sent"
                        if phase == "submitted"
                        else "unknown"
                        if phase == "submission_unknown"
                        else "released",
                        "message": sent.message_id if sent else None,
                        "id": rows[0]["claim_id"],
                    },
                )
        LOGGER.info(
            "email attempt completed channel=%s phase=%s",
            "system" if system else "subscriber",
            phase,
        )


def _complete_system(row: Mapping[str, Any], worker_id: str) -> None:
    _attempt_email([dict(row)], worker_id, system=True)


def _next_subscriber_target() -> dict[str, str] | None:
    now = utc_now()
    with transaction() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT o.email,
                    CASE WHEN t.tier = 'priority' AND t.revoked_at IS NULL THEN 'priority' ELSE 'standard' END AS tier,
                    slot.booking_date
                FROM zacks.notification_outbox o
                JOIN zacks.observed_slots slot ON slot.event_key = o.event_key
                LEFT JOIN zacks.user_delivery_tiers t ON t.email = o.email
                WHERE o.status IN ('pending', 'retry', 'processing')
                  AND o.next_attempt_at <= :now
                  AND (o.lease_until IS NULL OR o.lease_until <= :now)
                ORDER BY CASE WHEN t.tier = 'priority' AND t.revoked_at IS NULL THEN 0 ELSE 1 END, o.created_at
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
    return {
        "email": str(row["email"]),
        "tier": str(row["tier"]),
        "booking_date": row["booking_date"].isoformat(),
    }


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
                    SELECT o.id, o.email, o.subject, o.body, o.venue_id, o.event_key, o.attempt_count
                    FROM zacks.notification_outbox o
                    JOIN zacks.observed_slots slot ON slot.event_key = o.event_key
                    WHERE o.email = :email AND slot.booking_date = CAST(:booking_date AS date)
                      AND o.status IN ('pending', 'retry', 'processing')
                      AND o.next_attempt_at <= :now
                      AND (o.lease_until IS NULL OR o.lease_until <= :now)
                    ORDER BY o.created_at
                    FOR UPDATE OF o SKIP LOCKED
                    LIMIT :batch
                    """
                ),
                {
                    "email": target["email"],
                    "booking_date": target["booking_date"],
                    "now": now,
                    "batch": SUBSCRIBER_ROWS_PER_DIGEST,
                },
            ).mappings()
        ]
        if not rows:
            return []

        tier = "priority" if target["tier"] == "priority" else "standard"
        for row in rows:
            row["tier"] = tier
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
                      AND status IN ('reserved', 'unknown')
                      AND (status = 'unknown' OR updated_at > :reservation_cutoff)
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
                      AND status IN ('reserved', 'unknown')
                      AND (status = 'unknown' OR updated_at > :reservation_cutoff)
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
        connection.execute(
            text(
                "UPDATE zacks.notification_outbox SET delivery_claim_id = :claim WHERE id = ANY(:ids)"
            ),
            {"claim": claim_id, "ids": ids},
        )
        for row in rows:
            row["claim_id"] = claim_id
    return rows


def _complete_subscriber(rows: list[dict[str, Any]], worker_id: str) -> None:
    if rows:
        _attempt_email(rows, worker_id, system=False)


def _next_provider_check(
    table: str,
    message_column: str,
    email_column: str,
) -> dict[str, Any] | None:
    now = utc_now()
    retention_cutoff = now - timedelta(days=PROVIDER_RETENTION_DAYS)
    with transaction() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
            {"key": "zacks-provider-claim:" + table},
        )
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
        if row:
            connection.execute(
                text(
                    f"UPDATE zacks.{table} SET provider_next_check_at = :lease_until "
                    f"WHERE {message_column} = :message_id AND status = 'submitted'"
                ),
                {"lease_until": now + timedelta(seconds=60), "message_id": row["message_id"]},
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
            type(exc).__name__,
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
            type(exc).__name__,
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


def _reconcile(settings: HostCoreSettings, *, deadline: float | None = None) -> int:
    processed = 0
    for _ in range(RECONCILE_BATCH):
        if deadline is not None and time.monotonic() >= deadline:
            break
        subscriber = _next_provider_check("notification_outbox", "message_id", "email")
        if not subscriber:
            break
        _reconcile_subscriber_row(settings, subscriber)
        processed += 1
    for _ in range(RECONCILE_BATCH):
        if deadline is not None and time.monotonic() >= deadline:
            break
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
                    '你的网球提醒订阅将在 ' || to_char(subscriptions.active_until AT TIME ZONE 'Asia/Shanghai', 'YYYY-MM-DD HH24:MI')
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
                SET status = 'delivery_unknown',
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
                SET status = 'delivery_unknown',
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
            text("""
            UPDATE zacks.subscriptions SET active = false, updated_at = :now
            WHERE active AND NOT auto_renew AND active_until <= :now
        """),
            {"now": now},
        )


def _expire_unusable() -> None:
    with transaction() as connection:
        connection.execute(
            text("""
            UPDATE zacks.system_email_outbox SET status = 'expired', updated_at = now(),
                last_error = 'system_email_expired'
            WHERE status IN ('pending','retry','processing') AND
                COALESCE(expires_at, CASE WHEN email_type = 'verification'
                THEN created_at + interval '10 minutes' ELSE created_at + interval '1 day' END) <= now()
        """)
        )
        connection.execute(
            text("""
            UPDATE zacks.notification_outbox o SET status = 'expired', updated_at = now(),
                last_error = 'reminder_expired_or_cancelled'
            WHERE status IN ('pending','retry','processing') AND (
                created_at < now() - interval '15 minutes' OR NOT EXISTS (
                    SELECT 1 FROM zacks.subscriptions s JOIN zacks.observed_slots slot ON slot.event_key = o.event_key
                    LEFT JOIN zacks.user_delivery_tiers t ON t.email = s.email
                    WHERE s.id = o.subscription_id AND s.active AND s.active_until > now()
                    AND (NOT s.auto_renew OR (t.tier = 'priority' AND t.revoked_at IS NULL))
                    AND (slot.booking_date + CAST(slot.start_time AS time)) AT TIME ZONE 'Asia/Shanghai' > now()
                ))
        """)
        )


def run_cycle(worker_id: str, settings: HostCoreSettings) -> dict[str, int]:
    _expire_unusable()
    deadline = time.monotonic() + 30
    sent_system = 0
    sent_subscriber = 0
    for _ in range(SYSTEM_BATCH):
        if time.monotonic() >= deadline:
            break
        row = _claim_system(worker_id)
        if not row:
            break
        _complete_system(row, worker_id)
        sent_system += 1

    for _ in range(SUBSCRIBER_ROWS_PER_DIGEST):
        if time.monotonic() >= deadline:
            break
        target = _next_subscriber_target()
        if not target:
            break
        weather = evaluate_weather(settings, booking_date=target["booking_date"])
        rows = _claim_subscriber_group(worker_id, settings, target, weather)
        if not rows:
            continue
        _complete_subscriber(rows, worker_id)
        sent_subscriber += 1

    reconciled = _reconcile(settings, deadline=deadline)
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
        try:
            settings = load_settings()
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
            LOGGER.error("notification worker cycle failed: %s", type(exc).__name__)
            time.sleep(10)


if __name__ == "__main__":
    main()
