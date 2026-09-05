from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import uuid
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text

from .database import ensure_schema, transaction
from .domain import (
    ALL_WEEKDAY_MASK,
    encrypt_invite_code,
    hash_invite_code,
    subscription_dedupe_key,
    utc_now,
)
from .service import increment_subscription_generations
from .settings import load_settings

EXPORT_TABLES = (
    "verified_receipts",
    "user_profiles",
    "user_roles",
    "user_delivery_tiers",
    "priority_invite_codes",
    "priority_invite_attempts",
    "coffee_invite_sessions",
    "coffee_invite_claims",
    "subscriptions",
    "venue_status",
    "observed_slots",
    "subscription_events",
    "notification_outbox",
    "system_email_outbox",
    "email_delivery_claims",
)


def _dt(value: object, *, default: datetime | None = None) -> datetime | None:
    if value is None or value == "":
        return default
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    number: int | None = None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = int(value)
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    if number is not None:
        if number > 10_000_000_000:
            number //= 1_000
        try:
            return datetime.fromtimestamp(number, UTC)
        except (OSError, OverflowError, ValueError):
            return default
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return default
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _integer(value: object, default: int) -> int:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value or "[]"))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _fetch_table(
    session: requests.Session,
    base_url: str,
    token: str,
    table: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = 0
    while True:
        params: dict[str, str | int] = {
            "table": table,
            "cursor": cursor,
            "limit": 500,
        }
        response = session.get(
            f"{base_url.rstrip('/')}/api/internal/host-migration-export",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        batch = payload.get("rows") if isinstance(payload, dict) else None
        if not isinstance(batch, list):
            raise RuntimeError(f"migration export returned an invalid {table} page")
        rows.extend(dict(row) for row in batch if isinstance(row, Mapping))
        if payload.get("done") is True:
            break
        next_cursor = int(payload.get("nextCursor") or 0)
        if next_cursor <= cursor:
            raise RuntimeError(f"migration export cursor did not advance for {table}")
        cursor = next_cursor
    return rows


def fetch_snapshot(base_url: str, token: str) -> dict[str, list[dict[str, Any]]]:
    with requests.Session() as session:
        return {table: _fetch_table(session, base_url, token, table) for table in EXPORT_TABLES}


def _insert_receipts(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        connection.execute(
            text(
                """
                INSERT INTO zacks.verified_receipts(
                    token_hash, email, masked_email, expires_at, last_used_at,
                    created_at, revoked_at
                ) VALUES (
                    :token_hash, :email, :masked_email, :expires_at, :last_used_at,
                    :created_at, :revoked_at
                )
                ON CONFLICT (token_hash) DO UPDATE SET
                    expires_at = EXCLUDED.expires_at,
                    last_used_at = GREATEST(
                        zacks.verified_receipts.last_used_at,
                        EXCLUDED.last_used_at
                    ),
                    revoked_at = EXCLUDED.revoked_at
                """
            ),
            {
                "token_hash": row.get("token_hash"),
                "email": row.get("email"),
                "masked_email": row.get("masked_email"),
                "expires_at": _dt(row.get("expires_at"), default=now),
                "last_used_at": _dt(row.get("last_used_at"), default=now),
                "created_at": _dt(row.get("created_at"), default=now),
                "revoked_at": _dt(row.get("revoked_at")),
            },
        )


def _insert_profiles(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        connection.execute(
            text(
                """
                INSERT INTO zacks.user_profiles(
                    email, masked_email, first_verified_at, last_verified_at,
                    last_login_at, last_active_at, created_at, updated_at
                ) VALUES (
                    :email, :masked_email, :first_verified_at, :last_verified_at,
                    :last_login_at, :last_active_at, :created_at, :updated_at
                )
                ON CONFLICT (email) DO UPDATE SET
                    masked_email = EXCLUDED.masked_email,
                    first_verified_at = LEAST(
                        zacks.user_profiles.first_verified_at,
                        EXCLUDED.first_verified_at
                    ),
                    last_verified_at = GREATEST(
                        zacks.user_profiles.last_verified_at,
                        EXCLUDED.last_verified_at
                    ),
                    last_login_at = GREATEST(
                        zacks.user_profiles.last_login_at,
                        EXCLUDED.last_login_at
                    ),
                    last_active_at = GREATEST(
                        zacks.user_profiles.last_active_at,
                        EXCLUDED.last_active_at
                    ),
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "email": row.get("email"),
                "masked_email": row.get("masked_email"),
                "first_verified_at": _dt(row.get("first_verified_at"), default=now),
                "last_verified_at": _dt(row.get("last_verified_at"), default=now),
                "last_login_at": _dt(row.get("last_login_at"), default=now),
                "last_active_at": _dt(row.get("last_active_at"), default=now),
                "created_at": _dt(row.get("created_at"), default=now),
                "updated_at": _dt(row.get("updated_at"), default=now),
            },
        )


def _insert_roles(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        connection.execute(
            text(
                """
                INSERT INTO zacks.user_roles(
                    email, role, created_at, updated_at, revoked_at
                ) VALUES (:email, :role, :created_at, :updated_at, :revoked_at)
                ON CONFLICT (email, role) DO UPDATE SET
                    updated_at = EXCLUDED.updated_at,
                    revoked_at = EXCLUDED.revoked_at
                """
            ),
            {
                "email": row.get("email"),
                "role": row.get("role"),
                "created_at": _dt(row.get("created_at"), default=now),
                "updated_at": _dt(row.get("updated_at"), default=now),
                "revoked_at": _dt(row.get("revoked_at")),
            },
        )


def _insert_tiers(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        connection.execute(
            text(
                """
                INSERT INTO zacks.user_delivery_tiers(
                    email, tier, source_invite_id, created_at, updated_at, revoked_at
                ) VALUES (
                    :email, :tier, :source_invite_id, :created_at, :updated_at, :revoked_at
                )
                ON CONFLICT (email) DO UPDATE SET
                    tier = EXCLUDED.tier,
                    source_invite_id = EXCLUDED.source_invite_id,
                    updated_at = EXCLUDED.updated_at,
                    revoked_at = EXCLUDED.revoked_at
                """
            ),
            {
                "email": row.get("email"),
                "tier": row.get("tier") or "standard",
                "source_invite_id": row.get("source_invite_id"),
                "created_at": _dt(row.get("created_at"), default=now),
                "updated_at": _dt(row.get("updated_at"), default=now),
                "revoked_at": _dt(row.get("revoked_at")),
            },
        )


def _legacy_invite_plaintext(row: Mapping[str, Any], pepper: str) -> str | None:
    plaintext = str(row.get("plaintext_code") or "").strip()
    if plaintext:
        return plaintext
    ciphertext, iv = row.get("encrypted_code"), row.get("encryption_iv")
    if not ciphertext or not iv:
        return None

    def decode(value: object) -> bytes:
        encoded = str(value)
        return base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))

    try:
        key = hashlib.sha256(f"zacks-invite-encryption:{pepper}".encode()).digest()
        plaintext = AESGCM(key).decrypt(decode(iv), decode(ciphertext), None).decode()
        if hash_invite_code(plaintext, pepper) != row.get("code_hash"):
            raise ValueError("invite hash mismatch")
        return plaintext
    except Exception as exc:
        raise RuntimeError(
            "D1 invitation ciphertext could not be verified; migration aborted"
        ) from exc


class _BatchWriter:
    """Batch uniform insert statements; never defer SELECT/RETURNING or DDL."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.statement: Any = None
        self.parameters: list[dict[str, Any]] = []

    def flush(self) -> None:
        if self.parameters:
            # psycopg2 mogrify binds values safely; batch statements into one
            # round-trip instead of 40k individual network round-trips.
            if self.connection.dialect.driver == "psycopg2":
                compiled = str(self.statement.compile(dialect=self.connection.dialect))
                cursor = self.connection.connection.cursor()
                try:
                    cursor.execute(
                        b";".join(cursor.mogrify(compiled, values) for values in self.parameters)
                    )
                finally:
                    cursor.close()
            else:
                self.connection.execute(self.statement, self.parameters)
            self.parameters = []
            self.statement = None

    def execute(self, statement: Any, parameters: dict[str, Any] | None = None) -> Any:
        sql = str(statement)
        if (
            sql.lstrip().startswith("INSERT INTO")
            and "RETURNING" not in sql
            and parameters is not None
        ):
            if self.statement is not None and str(self.statement) != sql:
                self.flush()
            self.statement = statement
            self.parameters.append(parameters)
            if len(self.parameters) >= 1000:
                self.flush()
            return None
        self.flush()
        return self.connection.execute(statement, parameters or {})


def _insert_invites(connection, rows: Iterable[Mapping[str, Any]], pepper: str) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        plaintext = _legacy_invite_plaintext(row, pepper)
        encrypted = encrypt_invite_code(plaintext, pepper) if plaintext else None
        code_hash = (
            hash_invite_code(plaintext, pepper) if plaintext else str(row.get("code_hash") or "")
        )
        active = _boolean(row.get("active"))
        note = str(row.get("note") or "")[:120] or None
        connection.execute(
            text(
                """
                INSERT INTO zacks.priority_invite_codes(
                    id, code_hash, encrypted_code, code_hint, expires_at, active,
                    note, created_at, updated_at, redeemed_by, redeemed_at, deleted_at
                ) VALUES (
                    :id, :code_hash, :encrypted_code, :code_hint, :expires_at, :active,
                    :note, :created_at, :updated_at, :redeemed_by, :redeemed_at, :deleted_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    code_hash = EXCLUDED.code_hash,
                    encrypted_code = EXCLUDED.encrypted_code,
                    code_hint = EXCLUDED.code_hint,
                    expires_at = EXCLUDED.expires_at,
                    active = EXCLUDED.active,
                    note = EXCLUDED.note,
                    updated_at = EXCLUDED.updated_at,
                    redeemed_by = EXCLUDED.redeemed_by,
                    redeemed_at = EXCLUDED.redeemed_at,
                    deleted_at = EXCLUDED.deleted_at
                """
            ),
            {
                "id": row.get("id"),
                "code_hash": code_hash,
                "encrypted_code": encrypted,
                "code_hint": row.get("code_hint"),
                "expires_at": _dt(row.get("expires_at"), default=now),
                "active": active,
                "note": note,
                "created_at": _dt(row.get("created_at"), default=now),
                "updated_at": _dt(row.get("updated_at"), default=now),
                "redeemed_by": row.get("redeemed_by"),
                "redeemed_at": _dt(row.get("redeemed_at")),
                "deleted_at": _dt(row.get("deleted_at")),
            },
        )


def _insert_subscriptions(connection, rows: Iterable[Mapping[str, Any]]) -> set[str]:  # type: ignore[no-untyped-def]
    now = utc_now()
    affected: set[str] = set()
    for row in rows:
        venue_ids = _json_list(row.get("venue_ids"))
        mask = _integer(row.get("weekday_mask"), ALL_WEEKDAY_MASK)
        duration_days = _integer(row.get("duration_days"), 7)
        email = str(row.get("email") or "")
        dedupe_key = subscription_dedupe_key(
            email,
            venue_ids,
            str(row.get("start_time") or "00:00"),
            str(row.get("end_time") or "23:59"),
            mask,
        )
        active_until = _dt(row.get("active_until"), default=now) or now
        active = _boolean(row.get("active"))
        # Preserve an explicitly renewable priority subscription across an outage.
        if active and _boolean(row.get("auto_renew")) and active_until <= now:
            priority = connection.execute(
                text(
                    "SELECT EXISTS(SELECT 1 FROM zacks.user_delivery_tiers "
                    "WHERE email = :email AND tier = 'priority' AND revoked_at IS NULL)"
                ),
                {"email": email},
            ).scalar_one()
            if priority:
                active_until = now + timedelta(days=90)
        active = active and active_until > now
        connection.execute(
            text(
                """
                INSERT INTO zacks.subscriptions(
                    id, email, venue_ids, start_time, end_time, weekday_mask,
                    duration_days, term_code, auto_renew, dedupe_key,
                    active_until, active, created_at, updated_at
                ) VALUES (
                    :id, :email, CAST(:venue_ids AS jsonb), :start_time, :end_time,
                    :weekday_mask, :duration_days, :term_code, :auto_renew,
                    :dedupe_key, :active_until, :active, :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    email = EXCLUDED.email,
                    venue_ids = EXCLUDED.venue_ids,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    weekday_mask = EXCLUDED.weekday_mask,
                    duration_days = EXCLUDED.duration_days,
                    term_code = EXCLUDED.term_code,
                    auto_renew = EXCLUDED.auto_renew,
                    dedupe_key = EXCLUDED.dedupe_key,
                    active_until = EXCLUDED.active_until,
                    active = EXCLUDED.active,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "id": row.get("id"),
                "email": email,
                "venue_ids": json.dumps(venue_ids),
                "start_time": row.get("start_time") or "00:00",
                "end_time": row.get("end_time") or "23:59",
                "weekday_mask": mask,
                "duration_days": duration_days,
                "term_code": row.get("term_code") or f"{duration_days}d",
                "auto_renew": _boolean(row.get("auto_renew")),
                "dedupe_key": dedupe_key,
                "active_until": active_until,
                "active": active,
                "created_at": _dt(row.get("created_at"), default=now),
                "updated_at": _dt(row.get("updated_at"), default=now),
            },
        )
        connection.execute(
            text("DELETE FROM zacks.subscription_venues WHERE subscription_id = :id"),
            {"id": row.get("id")},
        )
        for venue_id in venue_ids:
            connection.execute(
                text(
                    """
                    INSERT INTO zacks.subscription_venues(subscription_id, venue_id)
                    VALUES (:subscription_id, :venue_id)
                    ON CONFLICT DO NOTHING
                    """
                ),
                {"subscription_id": row.get("id"), "venue_id": venue_id},
            )
            affected.add(venue_id)
    return affected


def _insert_venue_status(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        connection.execute(
            text(
                """
                INSERT INTO zacks.venue_status(
                    venue_id, venue_name, healthy, last_inspection_at,
                    last_notification_at, last_error, updated_at
                ) VALUES (
                    :venue_id, :venue_name, :healthy, :last_inspection_at,
                    :last_notification_at, :last_error, :updated_at
                )
                ON CONFLICT (venue_id) DO UPDATE SET
                    venue_name = EXCLUDED.venue_name,
                    healthy = EXCLUDED.healthy,
                    last_inspection_at = EXCLUDED.last_inspection_at,
                    last_notification_at = EXCLUDED.last_notification_at,
                    last_error = EXCLUDED.last_error,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "venue_id": row.get("venue_id"),
                "venue_name": row.get("venue_name"),
                "healthy": _boolean(row.get("healthy")),
                "last_inspection_at": _dt(row.get("last_inspection_at")),
                "last_notification_at": _dt(row.get("last_notification_at")),
                "last_error": row.get("last_error"),
                "updated_at": _dt(row.get("updated_at"), default=now),
            },
        )


def _insert_observed_slots(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        try:
            booking_date = date.fromisoformat(str(row.get("booking_date")))
        except ValueError as exc:
            raise RuntimeError("Invalid booking_date in D1 export") from exc
        connection.execute(
            text(
                """
                INSERT INTO zacks.observed_slots(
                    event_key, venue_id, court_name, booking_date, start_time,
                    end_time, first_observed_at, last_observed_at
                ) VALUES (
                    :event_key, :venue_id, :court_name, :booking_date, :start_time,
                    :end_time, :first_observed_at, :last_observed_at
                )
                ON CONFLICT (event_key) DO UPDATE SET
                    last_observed_at = GREATEST(
                        zacks.observed_slots.last_observed_at,
                        EXCLUDED.last_observed_at
                    )
                """
            ),
            {
                "event_key": row.get("event_key"),
                "venue_id": row.get("venue_id"),
                "court_name": row.get("court_name"),
                "booking_date": booking_date,
                "start_time": row.get("start_time"),
                "end_time": row.get("end_time"),
                "first_observed_at": _dt(row.get("first_observed_at"), default=now),
                "last_observed_at": _dt(row.get("last_observed_at"), default=now),
            },
        )


def _insert_subscription_events(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        connection.execute(
            text(
                """
                INSERT INTO zacks.subscription_events(subscription_id, event_key, created_at)
                VALUES (:subscription_id, :event_key, :created_at)
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "subscription_id": row.get("subscription_id"),
                "event_key": row.get("event_key"),
                "created_at": _dt(row.get("created_at"), default=now),
            },
        )


def _insert_notification_outbox(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        status = str(row.get("status") or "pending")
        if status == "processing":
            status = "submission_unknown"
        connection.execute(
            text(
                """
                INSERT INTO zacks.notification_outbox(
                    id, subscription_id, event_key, venue_id, email, subject, body,
                    tier, status, attempt_count, next_attempt_at, created_at, updated_at,
                    submitted_at, delivered_at, failed_at, message_id,
                    provider_request_id, provider_status, provider_checked_at,
                    provider_error, last_error
                ) VALUES (
                    :id, :subscription_id, :event_key, :venue_id, :email, :subject, :body,
                    :tier, :status, :attempt_count, :next_attempt_at, :created_at, :updated_at,
                    :submitted_at, :delivered_at, :failed_at, :message_id,
                    :provider_request_id, :provider_status, :provider_checked_at,
                    :provider_error, :last_error
                )
                ON CONFLICT (subscription_id, event_key) DO UPDATE SET
                    status = EXCLUDED.status,
                    attempt_count = EXCLUDED.attempt_count,
                    next_attempt_at = EXCLUDED.next_attempt_at,
                    submitted_at = EXCLUDED.submitted_at,
                    delivered_at = EXCLUDED.delivered_at,
                    failed_at = EXCLUDED.failed_at,
                    message_id = EXCLUDED.message_id,
                    provider_request_id = EXCLUDED.provider_request_id,
                    provider_status = EXCLUDED.provider_status,
                    provider_checked_at = EXCLUDED.provider_checked_at,
                    provider_error = EXCLUDED.provider_error,
                    last_error = EXCLUDED.last_error,
                    updated_at = EXCLUDED.updated_at,
                    lease_owner = NULL,
                    lease_until = NULL
                """
            ),
            {
                "id": row.get("id") or str(uuid.uuid4()),
                "subscription_id": row.get("subscription_id"),
                "event_key": row.get("event_key"),
                "venue_id": row.get("venue_id"),
                "email": row.get("email"),
                "subject": row.get("subject") or "网球空场提醒",
                "body": row.get("body") or row.get("subject") or "",
                "tier": row.get("tier") or "standard",
                "status": status,
                "attempt_count": int(row.get("attempt_count") or 0),
                "next_attempt_at": _dt(row.get("next_attempt_at"), default=now),
                "created_at": _dt(row.get("created_at"), default=now),
                "updated_at": _dt(row.get("updated_at"), default=now),
                "submitted_at": _dt(row.get("provider_submitted_at") or row.get("submitted_at")),
                "delivered_at": _dt(
                    row.get("provider_delivered_at")
                    or row.get("delivered_at")
                    or row.get("sent_at")
                ),
                "failed_at": _dt(row.get("provider_failed_at") or row.get("failed_at")),
                "message_id": row.get("message_id"),
                "provider_request_id": row.get("provider_request_id"),
                "provider_status": row.get("provider_status"),
                "provider_checked_at": _dt(row.get("provider_checked_at")),
                "provider_error": row.get("provider_error"),
                "last_error": row.get("last_error"),
            },
        )


def _insert_system_outbox(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        status = (
            "submission_unknown"
            if row.get("status") == "processing"
            else str(row.get("status") or "pending")
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.system_email_outbox(
                    id, dedupe_key, email, email_type, subject, body, status,
                    attempt_count, next_attempt_at, provider_message_id,
                    provider_request_id, provider_status, submitted_at, delivered_at,
                    failed_at, provider_checked_at, last_error, created_at, updated_at
                ) VALUES (
                    :id, :dedupe_key, :email, :email_type, :subject, :body, :status,
                    :attempt_count, :next_attempt_at, :provider_message_id,
                    :provider_request_id, :provider_status, :submitted_at, :delivered_at,
                    :failed_at, :provider_checked_at, :last_error, :created_at, :updated_at
                )
                ON CONFLICT (dedupe_key) DO UPDATE SET
                    status = EXCLUDED.status,
                    attempt_count = EXCLUDED.attempt_count,
                    next_attempt_at = EXCLUDED.next_attempt_at,
                    provider_message_id = EXCLUDED.provider_message_id,
                    provider_request_id = EXCLUDED.provider_request_id,
                    provider_status = EXCLUDED.provider_status,
                    submitted_at = EXCLUDED.submitted_at,
                    delivered_at = EXCLUDED.delivered_at,
                    failed_at = EXCLUDED.failed_at,
                    provider_checked_at = EXCLUDED.provider_checked_at,
                    last_error = EXCLUDED.last_error,
                    updated_at = EXCLUDED.updated_at,
                    lease_owner = NULL,
                    lease_until = NULL
                """
            ),
            {
                "id": row.get("id") or str(uuid.uuid4()),
                "dedupe_key": row.get("dedupe_key") or f"migrated:{row.get('id')}",
                "email": row.get("email"),
                "email_type": row.get("email_type") or "system",
                "subject": row.get("subject") or "Zacks 网球提醒",
                "body": row.get("body") or "",
                "status": status,
                "attempt_count": int(row.get("attempt_count") or 0),
                "next_attempt_at": _dt(row.get("next_attempt_at"), default=now),
                "provider_message_id": row.get("provider_message_id"),
                "provider_request_id": row.get("provider_request_id"),
                "provider_status": row.get("provider_status"),
                "submitted_at": _dt(row.get("submitted_at")),
                "delivered_at": _dt(row.get("delivered_at")),
                "failed_at": _dt(row.get("failed_at")),
                "provider_checked_at": _dt(row.get("provider_checked_at")),
                "last_error": row.get("last_error"),
                "created_at": _dt(row.get("created_at"), default=now),
                "updated_at": _dt(row.get("updated_at"), default=now),
            },
        )


def _insert_claims(connection, rows: Iterable[Mapping[str, Any]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in rows:
        connection.execute(
            text(
                """
                INSERT INTO zacks.email_delivery_claims(
                    id, email, delivery_day, status, message_id, created_at, updated_at
                ) VALUES (
                    :id, :email, CAST(:delivery_day AS date), :status, :message_id,
                    :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    message_id = EXCLUDED.message_id,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "id": row.get("id"),
                "email": row.get("email"),
                "delivery_day": row.get("delivery_day"),
                "status": row.get("status") or "released",
                "message_id": row.get("message_id"),
                "created_at": _dt(row.get("created_at"), default=now),
                "updated_at": _dt(row.get("updated_at"), default=now),
            },
        )


def _insert_generic_audit_rows(connection, snapshot: Mapping[str, list[dict[str, Any]]]) -> None:  # type: ignore[no-untyped-def]
    now = utc_now()
    for row in snapshot.get("priority_invite_attempts", []):
        connection.execute(
            text(
                """
                INSERT INTO zacks.priority_invite_attempts(
                    id, email, ip_hash, success, created_at
                ) VALUES (:id, :email, :ip_hash, :success, :created_at)
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": row.get("id"),
                "email": row.get("email"),
                "ip_hash": row.get("ip_hash"),
                "success": _boolean(row.get("success")),
                "created_at": _dt(row.get("created_at"), default=now),
            },
        )
    for row in snapshot.get("coffee_invite_sessions", []):
        connection.execute(
            text(
                """
                INSERT INTO zacks.coffee_invite_sessions(
                    id, email, ip_hash, shown_at, claimable_at, expires_at,
                    consumed_at, created_at
                ) VALUES (
                    :id, :email, :ip_hash, :shown_at, :claimable_at, :expires_at,
                    :consumed_at, :created_at
                ) ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": row.get("id"),
                "email": row.get("email"),
                "ip_hash": row.get("ip_hash"),
                "shown_at": _dt(row.get("shown_at"), default=now),
                "claimable_at": _dt(row.get("claimable_at"), default=now),
                "expires_at": _dt(row.get("expires_at"), default=now),
                "consumed_at": _dt(row.get("consumed_at")),
                "created_at": _dt(row.get("created_at"), default=now),
            },
        )
    for row in snapshot.get("coffee_invite_claims", []):
        connection.execute(
            text(
                """
                INSERT INTO zacks.coffee_invite_claims(
                    email, session_id, invite_id, ip_hash, claimed_at
                ) VALUES (
                    :email, :session_id, :invite_id, :ip_hash, :claimed_at
                ) ON CONFLICT (email) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    invite_id = EXCLUDED.invite_id,
                    ip_hash = EXCLUDED.ip_hash,
                    claimed_at = EXCLUDED.claimed_at
                """
            ),
            {
                "email": row.get("email"),
                "session_id": row.get("session_id"),
                "invite_id": row.get("invite_id"),
                "ip_hash": row.get("ip_hash"),
                "claimed_at": _dt(row.get("claimed_at"), default=now),
            },
        )


RECONCILIATION_KEYS: dict[str, tuple[str, ...]] = {
    "verified_receipts": ("token_hash",),
    "user_profiles": ("email",),
    "user_roles": ("email", "role"),
    "user_delivery_tiers": ("email",),
    "priority_invite_codes": ("id",),
    "priority_invite_attempts": ("id",),
    "coffee_invite_sessions": ("id",),
    "coffee_invite_claims": ("email",),
    "subscriptions": ("id",),
    "venue_status": ("venue_id",),
    "observed_slots": ("event_key",),
    "subscription_events": ("subscription_id", "event_key"),
    "notification_outbox": ("subscription_id", "event_key"),
    "system_email_outbox": ("dedupe_key",),
    "email_delivery_claims": ("id",),
}


def reconcile_snapshot(
    connection: Any, snapshot: Mapping[str, list[dict[str, Any]]]
) -> dict[str, Any]:
    proof: dict[str, Any] = {}
    for table, columns in RECONCILIATION_KEYS.items():
        # Table/column identifiers come exclusively from the fixed manifest above.
        source_keys = {
            tuple(str(row.get(c) or "") for c in columns) for row in snapshot.get(table, [])
        }
        destination_keys = {
            tuple(str(value or "") for value in row)
            for row in connection.execute(text(f"SELECT {', '.join(columns)} FROM zacks.{table}"))
        }
        missing = source_keys - destination_keys
        if missing:
            raise RuntimeError(
                f"Migration reconciliation failed for {table}: {len(missing)} missing keys"
            )
        canonical = json.dumps(sorted(source_keys), ensure_ascii=False, separators=(",", ":"))
        proof[table] = {
            "sourceCount": len(source_keys),
            "matchedCount": len(source_keys),
            "keysSha256": hashlib.sha256(canonical.encode()).hexdigest(),
        }
    # Same event identity must keep its previously acknowledged provider message ID.
    destination = {
        (str(r["subscription_id"]), str(r["event_key"])): r
        for r in connection.execute(
            text(
                "SELECT subscription_id, event_key, message_id, status FROM zacks.notification_outbox"
            )
        ).mappings()
    }
    for row in snapshot.get("notification_outbox", []):
        target = destination[(str(row["subscription_id"]), str(row["event_key"]))]
        if (row.get("message_id") or None) != (target["message_id"] or None):
            raise RuntimeError("Provider message identity changed during migration")
        expected = (
            "submission_unknown"
            if row.get("status") == "processing"
            else (row.get("status") or "pending")
        )
        if target["status"] != expected:
            raise RuntimeError("Notification status changed during migration")
    proof["providerIdentityPreserved"] = True
    return proof


def import_snapshot(
    snapshot: Mapping[str, list[dict[str, Any]]],
    *,
    source_revision: str,
) -> dict[str, int]:
    settings = load_settings()
    ensure_schema()
    counts = {table: len(snapshot.get(table, [])) for table in EXPORT_TABLES}
    now = utc_now()
    with transaction() as connection:
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('zacks-d1-import-v1'))"))
        state = (
            connection.execute(
                text("SELECT * FROM zacks.runtime_control WHERE singleton FOR UPDATE")
            )
            .mappings()
            .one()
        )
        if state["activated_at"] is not None or state["delivery_enabled"]:
            raise RuntimeError("Source import is forbidden after Host Core activation")
        connection.execute(
            text(
                "UPDATE zacks.subscriptions SET active = false WHERE active_until <= now() AND NOT auto_renew"
            )
        )
        batch = _BatchWriter(connection)
        _insert_profiles(batch, snapshot.get("user_profiles", []))
        _insert_roles(batch, snapshot.get("user_roles", []))
        _insert_tiers(batch, snapshot.get("user_delivery_tiers", []))
        _insert_receipts(batch, snapshot.get("verified_receipts", []))
        _insert_invites(batch, snapshot.get("priority_invite_codes", []), settings.invite_pepper)
        affected = _insert_subscriptions(batch, snapshot.get("subscriptions", []))
        _insert_venue_status(batch, snapshot.get("venue_status", []))
        _insert_observed_slots(batch, snapshot.get("observed_slots", []))
        _insert_subscription_events(batch, snapshot.get("subscription_events", []))
        _insert_notification_outbox(batch, snapshot.get("notification_outbox", []))
        _insert_system_outbox(batch, snapshot.get("system_email_outbox", []))
        _insert_claims(batch, snapshot.get("email_delivery_claims", []))
        _insert_generic_audit_rows(batch, snapshot)
        batch.flush()
        proof = reconcile_snapshot(connection, snapshot)
        for table in ("notification_outbox", "system_email_outbox"):
            connection.execute(
                text(f"""
                UPDATE zacks.{table} SET provider_next_check_at = now()
                WHERE status = 'submitted' AND provider_next_check_at IS NULL
            """)
            )
        increment_subscription_generations(connection, sorted(affected))
        connection.execute(
            text(
                """
                INSERT INTO zacks.migration_state(
                    source, source_revision, imported_at, details, updated_at
                ) VALUES (
                    'cloudflare-d1', :source_revision, :imported_at,
                    CAST(:details AS jsonb), :updated_at
                )
                ON CONFLICT (source) DO UPDATE SET
                    source_revision = EXCLUDED.source_revision,
                    imported_at = EXCLUDED.imported_at,
                    details = EXCLUDED.details,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "source_revision": source_revision,
                "imported_at": now,
                "details": json.dumps(
                    {"counts": counts, "reconciliation": proof}, separators=(",", ":")
                ),
                "updated_at": now,
            },
        )
    return counts


def _default_token() -> str:
    configured = os.environ.get("ZACKS_MIGRATION_TOKEN", "").strip()
    if configured:
        return configured
    try:
        from airflow.sdk import Variable

        return str(Variable.get("WEBAPP_OBSERVATION_API_TOKEN")).strip()
    except Exception as exc:
        raise RuntimeError("migration token is unavailable") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate Cloudflare D1 data to host PostgreSQL")
    parser.add_argument("--base-url", default="https://zacks.claude89757.cc")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--snapshot-output")
    parser.add_argument("--snapshot-input")
    parser.add_argument("--fetch-only", action="store_true")
    arguments = parser.parse_args(argv)

    if arguments.snapshot_input:
        snapshot = json.loads(open(arguments.snapshot_input, encoding="utf-8").read())
    else:
        snapshot = fetch_snapshot(arguments.base_url, _default_token())
    if not isinstance(snapshot, dict):
        raise RuntimeError("migration snapshot is invalid")
    if arguments.snapshot_output:
        with open(arguments.snapshot_output, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        os.chmod(arguments.snapshot_output, 0o600)
    if arguments.fetch_only:
        return 0
    counts = import_snapshot(snapshot, source_revision=arguments.source_revision)
    print(json.dumps({"success": True, "counts": counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
