"""Per-email booking-date preferences, independent of subscription and tier."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .control import DELIVERY_LOCK
from .domain import SHANGHAI, utc_now

MAX_PAUSE_DAYS = 365
MAX_DATES_PER_REQUEST = 31
PAUSE_REASON = "booking_date_paused"


def validate_pause_request(payload: object, now: datetime) -> tuple[str, list[date]]:
    if not isinstance(payload, dict) or set(payload) != {"action", "dates"}:
        raise ValueError("请提供暂停或恢复操作和日期列表")
    action = payload.get("action")
    if action not in ("pause", "resume"):
        raise ValueError("请选择暂停或恢复提醒")
    raw_dates = payload.get("dates")
    if not isinstance(raw_dates, list) or not 1 <= len(raw_dates) <= MAX_DATES_PER_REQUEST:
        raise ValueError("每次请选择 1 至 31 个日期")
    today = now.astimezone(SHANGHAI).date()
    dates: set[date] = set()
    for raw in raw_dates:
        if not isinstance(raw, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            raise ValueError("日期格式应为 YYYY-MM-DD")
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError("请选择有效日期") from exc
        if not today <= parsed <= today + timedelta(days=MAX_PAUSE_DAYS):
            raise ValueError("请选择今天起 365 天内的日期")
        dates.add(parsed)
    return action, sorted(dates)


def read_pauses(connection: Connection, email: str, now: datetime | None = None) -> dict[str, Any]:
    today = (now or utc_now()).astimezone(SHANGHAI).date()
    dates = connection.execute(
        text("""
        SELECT booking_date FROM zacks.notification_date_pauses
        WHERE email = :email AND paused AND booking_date >= :today
        ORDER BY booking_date
        """),
        {"email": email, "today": today},
    ).scalars()
    return {
        "pausedDates": [day.isoformat() for day in dates],
        "today": today.isoformat(),
        "timezone": "Asia/Shanghai",
    }


def lock_pause_reads(connection: Connection) -> None:
    # Always acquire this BEFORE observation, outbox or quota locks. Mutations
    # take the exclusive counterpart, also used by the existing delivery fence.
    connection.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": DELIVERY_LOCK})


def release_unused_claims(connection: Connection, claim_ids: list[str], now: datetime) -> None:
    if not claim_ids:
        return
    connection.execute(
        text("""
        UPDATE zacks.email_delivery_claims claim
        SET status = 'released', updated_at = :now
        WHERE claim.id = ANY(:ids) AND claim.status = 'reserved' AND claim.message_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM zacks.notification_outbox o
            WHERE o.delivery_claim_id = claim.id
              AND (o.status NOT IN ('cancelled', 'expired', 'suppressed', 'failed')
                OR o.submitted_at IS NOT NULL OR o.message_id IS NOT NULL)
          )
          AND NOT EXISTS (
            SELECT 1 FROM zacks.notification_outbox o
            JOIN zacks.delivery_attempts a ON a.queue_ids ? o.id
            WHERE o.delivery_claim_id = claim.id AND a.channel = 'subscriber_email'
              AND a.phase NOT IN ('retry', 'failed')
          )
        """),
        {"ids": claim_ids, "now": now},
    )


def update_pauses(connection: Connection, email: str, payload: object) -> dict[str, Any]:
    # A successful response is after in-flight sends have completed and before
    # any new observation, claim or send can cross the preference change.
    connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DELIVERY_LOCK})
    now = utc_now()
    action, dates = validate_pause_request(payload, now)
    if action == "pause":
        changed = (
            connection.execute(
                text("""
            INSERT INTO zacks.notification_date_pauses(email, booking_date, paused, created_at, updated_at)
            SELECT :email, day, true, :now, :now FROM unnest(CAST(:dates AS date[])) AS day
            ON CONFLICT (email, booking_date) DO UPDATE
                SET paused = true, updated_at = EXCLUDED.updated_at
                WHERE NOT zacks.notification_date_pauses.paused
            RETURNING booking_date
            """),
                {"email": email, "dates": dates, "now": now},
            )
            .scalars()
            .all()
        )
        cancelled = (
            connection.execute(
                text("""
            UPDATE zacks.notification_outbox o
            SET status = 'cancelled', last_error = :reason, updated_at = :now,
                lease_owner = NULL, lease_until = NULL
            FROM zacks.observed_slots slot
            WHERE o.event_key = slot.event_key AND o.email = :email
              AND slot.booking_date = ANY(:dates)
              AND o.status IN ('pending', 'retry', 'processing')
              AND o.submitted_at IS NULL AND o.message_id IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM zacks.delivery_attempts a
                WHERE a.channel = 'subscriber_email' AND a.queue_ids ? o.id
                  AND a.phase NOT IN ('retry', 'failed')
              )
            RETURNING o.delivery_claim_id
            """),
                {"email": email, "dates": dates, "reason": PAUSE_REASON, "now": now},
            )
            .scalars()
            .all()
        )
        release_unused_claims(connection, sorted({claim for claim in cancelled if claim}), now)
    else:
        changed = (
            connection.execute(
                text("""
            UPDATE zacks.notification_date_pauses
            SET paused = false, updated_at = :now
            WHERE email = :email AND booking_date = ANY(:dates) AND paused
            RETURNING booking_date
            """),
                {"email": email, "dates": dates, "now": now},
            )
            .scalars()
            .all()
        )
    return {
        **read_pauses(connection, email, now),
        "changedDates": sorted(day.isoformat() for day in changed),
    }


def observation_rules(
    connection: Connection, emails: list[str], dates: list[date]
) -> dict[tuple[str, date], Mapping[str, Any]]:
    if not emails or not dates:
        return {}
    rows = connection.execute(
        text("""
        SELECT email, booking_date, paused, updated_at
        FROM zacks.notification_date_pauses
        WHERE email = ANY(:emails) AND booking_date = ANY(:dates)
        """),
        {"emails": emails, "dates": dates},
    ).mappings()
    return {(str(row["email"]), row["booking_date"]): dict(row) for row in rows}


def needs_resume_match(
    rules: Iterable[Mapping[str, Any]], last_seen_at: datetime, now: datetime
) -> bool:
    # An old observation arriving just after resume must not consume the
    # generation change and prevent the next fresh, identical poll matching.
    return any(
        not rule["paused"]
        and (last_seen_at <= rule["updated_at"] or last_seen_at < now - timedelta(minutes=15))
        for rule in rules
    )


def rule_allows_observation(
    rule: Mapping[str, Any] | None, checked_at: datetime, now: datetime
) -> bool:
    return rule is None or (
        not rule["paused"]
        and checked_at > rule["updated_at"]
        and checked_at > now - timedelta(minutes=15)
    )


def restore_paused_notification(
    connection: Connection,
    subscription_id: str,
    event_key: str,
    checked_at: datetime,
    now: datetime,
    tier: str,
) -> bool:
    # Called ONLY after a fresh, post-resume observation passed all current
    # subscription/date/time rules. Keep the original event and created_at;
    # eligible_at gives this new qualification its own bounded lifetime.
    row = connection.execute(
        text("""
        UPDATE zacks.notification_outbox o
        SET status = 'pending', last_error = NULL, eligible_at = :seen,
            next_attempt_at = :due, updated_at = :now, tier = :tier,
            lease_owner = NULL, lease_until = NULL, delivery_claim_id = NULL
        WHERE subscription_id = :subscription AND event_key = :event
          AND status = 'cancelled' AND last_error = :reason
          AND submitted_at IS NULL AND message_id IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM zacks.delivery_attempts a
            WHERE a.channel = 'subscriber_email' AND a.queue_ids ? o.id
              AND a.phase NOT IN ('retry', 'failed')
          )
        RETURNING id
        """),
        {
            "subscription": subscription_id,
            "event": event_key,
            "reason": PAUSE_REASON,
            "seen": checked_at,
            "now": now,
            "tier": tier,
            "due": now if tier == "priority" else now + timedelta(seconds=10),
        },
    ).scalar_one_or_none()
    return row is not None
