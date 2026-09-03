from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Mapping, Sequence

from sqlalchemy import bindparam, text
from sqlalchemy.engine import Connection

from wechat_airflow.notification_core.config import NotificationCoreSettings, load_settings
from wechat_airflow.notification_core.database import transaction
from wechat_airflow.notification_core.domain import (
    NormalizedSlot,
    event_key_for,
    format_slot_line,
    normalize_observation,
    normalize_subscription,
    parse_datetime,
    slot_matches_subscription,
)


@dataclass(frozen=True)
class EmailDigestClaim:
    lease_id: uuid.UUID
    row_ids: tuple[uuid.UUID, ...]
    email: str
    tier: str
    subject: str
    body: str


@dataclass(frozen=True)
class SubmittedMessage:
    message_id: str
    email: str
    row_ids: tuple[uuid.UUID, ...]
    submitted_at: datetime


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _event_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    rows: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        candidate = {str(key): raw for key, raw in item.items()}
        subscription_id = str(
            candidate.get("subscriptionId") or candidate.get("subscription_id") or ""
        ).strip()
        event_key = str(candidate.get("eventKey") or candidate.get("event_key") or "").strip()
        if not subscription_id or not event_key:
            continue
        created = candidate.get("createdAt") or candidate.get("created_at")
        rows.append(
            {
                "subscription_id": subscription_id[:120],
                "event_key": event_key[:128],
                "source_created_at": (
                    parse_datetime(created, field="created_at") if created else None
                ),
            }
        )
    return rows[:100_000]


def synchronize_subscription_snapshot(
    payload: object,
    settings: NotificationCoreSettings | None = None,
) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("subscription snapshot must be an object")
    candidate = {str(key): value for key, value in payload.items()}
    revision = str(candidate.get("revision") or "").strip()
    if not revision:
        raise ValueError("subscription snapshot revision is required")
    generated_at = parse_datetime(
        candidate.get("generatedAt") or candidate.get("generated_at"),
        field="generated_at",
    )
    raw_subscriptions = candidate.get("subscriptions")
    if not isinstance(raw_subscriptions, Sequence) or isinstance(
        raw_subscriptions, (str, bytes, bytearray)
    ):
        raise ValueError("subscriptions must be an array")
    subscriptions = [normalize_subscription(value) for value in raw_subscriptions]
    events = _event_rows(candidate.get("subscriptionEvents") or candidate.get("events"))
    resolved = settings or load_settings()

    with transaction(resolved) as connection:
        for subscription in subscriptions:
            connection.execute(
                text(
                    """
                    INSERT INTO subscriptions(
                        id, email, weekday_mask, start_minute, end_minute, tier,
                        auto_renew, active_until, source_updated_at,
                        snapshot_revision, synced_at
                    ) VALUES (
                        :id, :email, :weekday_mask, :start_minute, :end_minute, :tier,
                        :auto_renew, :active_until, :source_updated_at,
                        :snapshot_revision, now()
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        email = EXCLUDED.email,
                        weekday_mask = EXCLUDED.weekday_mask,
                        start_minute = EXCLUDED.start_minute,
                        end_minute = EXCLUDED.end_minute,
                        tier = EXCLUDED.tier,
                        auto_renew = EXCLUDED.auto_renew,
                        active_until = EXCLUDED.active_until,
                        source_updated_at = EXCLUDED.source_updated_at,
                        snapshot_revision = EXCLUDED.snapshot_revision,
                        synced_at = now()
                    """
                ),
                {
                    "id": subscription.subscription_id,
                    "email": subscription.email,
                    "weekday_mask": subscription.weekday_mask,
                    "start_minute": subscription.start_minute,
                    "end_minute": subscription.end_minute,
                    "tier": subscription.tier,
                    "auto_renew": subscription.auto_renew,
                    "active_until": subscription.active_until,
                    "source_updated_at": subscription.updated_at,
                    "snapshot_revision": revision,
                },
            )
            connection.execute(
                text("DELETE FROM subscription_venues WHERE subscription_id = :id"),
                {"id": subscription.subscription_id},
            )
            connection.execute(
                text(
                    "INSERT INTO subscription_venues(subscription_id, venue_id) "
                    "VALUES (:subscription_id, :venue_id)"
                ),
                [
                    {
                        "subscription_id": subscription.subscription_id,
                        "venue_id": venue_id,
                    }
                    for venue_id in subscription.venue_ids
                ],
            )

        connection.execute(
            text("DELETE FROM subscriptions WHERE snapshot_revision <> :revision"),
            {"revision": revision},
        )
        if events:
            connection.execute(
                text(
                    """
                    INSERT INTO subscription_events(
                        subscription_id, event_key, source_created_at, imported
                    ) VALUES (
                        :subscription_id, :event_key, :source_created_at, TRUE
                    )
                    ON CONFLICT (subscription_id, event_key) DO NOTHING
                    """
                ),
                events,
            )
        connection.execute(
            text(
                """
                UPDATE subscription_snapshot_state
                   SET revision = :revision,
                       source_generated_at = :generated_at,
                       synced_at = now(),
                       ready = TRUE,
                       source_count = :source_count,
                       last_error = NULL
                 WHERE singleton = TRUE
                """
            ),
            {
                "revision": revision,
                "generated_at": generated_at,
                "source_count": len(subscriptions),
            },
        )
    return {
        "revision": revision,
        "subscriptions": len(subscriptions),
        "subscriptionEvents": len(events),
    }


def record_snapshot_error(
    reason: str,
    settings: NotificationCoreSettings | None = None,
) -> None:
    resolved = settings or load_settings()
    with transaction(resolved) as connection:
        connection.execute(
            text(
                "UPDATE subscription_snapshot_state SET last_error = :reason "
                "WHERE singleton = TRUE"
            ),
            {"reason": reason[:500]},
        )


def _gate_for_venue(
    connection: Connection,
    venue_id: str,
    settings: NotificationCoreSettings,
    now: datetime,
) -> dict[str, object]:
    state = connection.execute(
        text(
            "SELECT revision, ready, synced_at FROM subscription_snapshot_state "
            "WHERE singleton = TRUE"
        )
    ).mappings().one()
    ready = bool(state["ready"])
    synced_at = state["synced_at"]
    authoritative = bool(
        ready
        and synced_at
        and synced_at >= now - timedelta(seconds=settings.subscription_sync_seconds * 3)
    )
    count = 0
    if ready:
        count = int(
            connection.execute(
                text(
                    """
                    SELECT COUNT(DISTINCT s.id)
                      FROM subscriptions s
                      JOIN subscription_venues sv ON sv.subscription_id = s.id
                     WHERE sv.venue_id = :venue_id
                       AND s.active_until > :now
                       AND (s.auto_renew = FALSE OR s.tier = 'priority')
                    """
                ),
                {"venue_id": venue_id, "now": now},
            ).scalar_one()
            or 0
        )
    # Unknown/stale state must not stop the independent WeChat channel.
    allowed = count > 0 if authoritative else True
    valid_until = now + timedelta(seconds=settings.subscription_sync_seconds * 3)
    return {
        "allowed": allowed,
        "authoritative": authoritative,
        "activeSubscriptionCount": count,
        "revision": str(state["revision"]),
        "evaluatedAt": now.isoformat(),
        "validUntil": valid_until.isoformat(),
    }


def _upsert_availability(
    connection: Connection,
    venue_id: str,
    venue_name: str,
    checked_at: datetime,
    slot: NormalizedSlot,
) -> str:
    event_key = event_key_for(venue_id, slot)
    connection.execute(
        text(
            """
            INSERT INTO availability_events(
                event_key, venue_id, venue_name, booking_date, court_name,
                start_minute, end_minute, first_observed_at, last_observed_at
            ) VALUES (
                :event_key, :venue_id, :venue_name, :booking_date, :court_name,
                :start_minute, :end_minute, :checked_at, :checked_at
            )
            ON CONFLICT (event_key) DO UPDATE SET
                venue_name = EXCLUDED.venue_name,
                last_observed_at = GREATEST(
                    availability_events.last_observed_at,
                    EXCLUDED.last_observed_at
                )
            """
        ),
        {
            "event_key": event_key,
            "venue_id": venue_id,
            "venue_name": venue_name,
            "booking_date": slot.booking_date,
            "court_name": slot.court_name,
            "start_minute": slot.start_minute,
            "end_minute": slot.end_minute,
            "checked_at": checked_at,
        },
    )
    return event_key


def ingest_observation(
    payload: object,
    settings: NotificationCoreSettings | None = None,
) -> dict[str, object]:
    observation = normalize_observation(payload)
    resolved = settings or load_settings()
    now = _utcnow()
    matched = 0

    with transaction(resolved) as connection:
        connection.execute(
            text(
                """
                INSERT INTO venue_status(
                    venue_id, venue_name, healthy, last_inspection_at,
                    last_error, last_fingerprint, updated_at
                ) VALUES (
                    :venue_id, :venue_name, :healthy, :checked_at,
                    :last_error, :fingerprint, now()
                )
                ON CONFLICT (venue_id) DO UPDATE SET
                    venue_name = EXCLUDED.venue_name,
                    healthy = EXCLUDED.healthy,
                    last_inspection_at = EXCLUDED.last_inspection_at,
                    last_error = EXCLUDED.last_error,
                    last_fingerprint = EXCLUDED.last_fingerprint,
                    updated_at = now()
                """
            ),
            {
                "venue_id": observation.venue_id,
                "venue_name": observation.venue_name,
                "healthy": observation.healthy,
                "checked_at": observation.checked_at,
                "last_error": observation.error,
                "fingerprint": observation.fingerprint,
            },
        )
        gate = _gate_for_venue(connection, observation.venue_id, resolved, now)
        revision = str(gate["revision"])
        inserted = connection.execute(
            text(
                """
                INSERT INTO observation_receipts(
                    venue_id, fingerprint, snapshot_revision,
                    first_seen_at, last_seen_at
                ) VALUES (
                    :venue_id, :fingerprint, :revision, now(), now()
                )
                ON CONFLICT (venue_id, fingerprint, snapshot_revision)
                DO NOTHING
                RETURNING 1
                """
            ),
            {
                "venue_id": observation.venue_id,
                "fingerprint": observation.fingerprint,
                "revision": revision,
            },
        ).scalar_one_or_none()
        if not inserted:
            connection.execute(
                text(
                    """
                    UPDATE observation_receipts SET last_seen_at = now()
                     WHERE venue_id = :venue_id
                       AND fingerprint = :fingerprint
                       AND snapshot_revision = :revision
                    """
                ),
                {
                    "venue_id": observation.venue_id,
                    "fingerprint": observation.fingerprint,
                    "revision": revision,
                },
            )
            return {
                "success": True,
                "venueId": observation.venue_id,
                "slotsAccepted": len(observation.slots),
                "deduplicated": True,
                "matchedNotifications": 0,
                "wechatGate": gate,
            }

        if observation.healthy and observation.slots:
            subscription_rows = connection.execute(
                text(
                    """
                    SELECT s.id, s.email, s.weekday_mask, s.start_minute,
                           s.end_minute, s.tier
                      FROM subscriptions s
                      JOIN subscription_venues sv ON sv.subscription_id = s.id
                     WHERE sv.venue_id = :venue_id
                       AND s.active_until > :now
                       AND (s.auto_renew = FALSE OR s.tier = 'priority')
                    """
                ),
                {"venue_id": observation.venue_id, "now": now},
            ).mappings().all()

            for slot in observation.slots:
                event_key = _upsert_availability(
                    connection,
                    observation.venue_id,
                    observation.venue_name,
                    observation.checked_at,
                    slot,
                )
                line = format_slot_line(observation.venue_name, slot)
                for subscription in subscription_rows:
                    if not slot_matches_subscription(
                        slot,
                        weekday_mask=int(subscription["weekday_mask"]),
                        start_minute=int(subscription["start_minute"]),
                        end_minute=int(subscription["end_minute"]),
                    ):
                        continue
                    outbox_id = uuid.uuid4()
                    created = connection.execute(
                        text(
                            """
                            WITH claimed AS (
                                INSERT INTO subscription_events(
                                    subscription_id, event_key, imported
                                ) VALUES (:subscription_id, :event_key, FALSE)
                                ON CONFLICT (subscription_id, event_key) DO NOTHING
                                RETURNING 1
                            )
                            INSERT INTO email_outbox(
                                id, dedupe_key, subscription_id, event_key,
                                venue_id, email, tier, subject, body
                            )
                            SELECT :id, :dedupe_key, :subscription_id, :event_key,
                                   :venue_id, :email, :tier, :subject, :body
                              FROM claimed
                            ON CONFLICT (dedupe_key) DO NOTHING
                            RETURNING 1
                            """
                        ),
                        {
                            "id": outbox_id,
                            "dedupe_key": (
                                f"email:{subscription['id']}:{event_key}"
                            ),
                            "subscription_id": subscription["id"],
                            "event_key": event_key,
                            "venue_id": observation.venue_id,
                            "email": subscription["email"],
                            "tier": subscription["tier"],
                            "subject": line,
                            "body": line,
                        },
                    ).scalar_one_or_none()
                    matched += 1 if created else 0

        connection.execute(
            text(
                """
                UPDATE observation_receipts SET match_count = :match_count
                 WHERE venue_id = :venue_id
                   AND fingerprint = :fingerprint
                   AND snapshot_revision = :revision
                """
            ),
            {
                "match_count": matched,
                "venue_id": observation.venue_id,
                "fingerprint": observation.fingerprint,
                "revision": revision,
            },
        )

    return {
        "success": True,
        "venueId": observation.venue_id,
        "slotsAccepted": len(observation.slots),
        "deduplicated": False,
        "matchedNotifications": matched,
        "wechatGate": gate,
    }


def recover_expired_processing(
    settings: NotificationCoreSettings | None = None,
) -> int:
    resolved = settings or load_settings()
    with transaction(resolved) as connection:
        rows = connection.execute(
            text(
                """
                UPDATE email_outbox
                   SET status = 'uncertain',
                       lease_id = NULL,
                       lease_until = NULL,
                       last_error = 'delivery worker lease expired; not replayed automatically',
                       updated_at = now()
                 WHERE status = 'processing'
                   AND lease_until < now()
                RETURNING id
                """
            )
        ).scalars().all()
        for row_id in rows:
            connection.execute(
                text(
                    """
                    INSERT INTO delivery_incidents(
                        id, channel, severity, dedupe_key, reference_id,
                        summary, detail
                    ) VALUES (
                        :id, 'email', 'error', :dedupe_key, :reference_id,
                        '邮件发送租约过期，已停止自动重放',
                        '发送结果可能不确定，需要供应商对账或人工处理。'
                    )
                    ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "dedupe_key": f"expired-lease:{row_id}",
                    "reference_id": str(row_id),
                },
            )
    return len(rows)


def claim_email_digest(
    settings: NotificationCoreSettings | None = None,
    *,
    max_rows: int = 20,
) -> EmailDigestClaim | None:
    resolved = settings or load_settings()
    max_rows = min(max(1, int(max_rows)), 50)
    lease_id = uuid.uuid4()
    with transaction(resolved) as connection:
        first = connection.execute(
            text(
                """
                SELECT id, email, tier
                  FROM email_outbox
                 WHERE status IN ('pending', 'retry')
                   AND next_attempt_at <= now()
                 ORDER BY CASE WHEN tier = 'priority' THEN 0 ELSE 1 END,
                          created_at
                 FOR UPDATE SKIP LOCKED
                 LIMIT 1
                """
            )
        ).mappings().first()
        if not first:
            return None
        rows = connection.execute(
            text(
                """
                SELECT id, subject, body
                  FROM email_outbox
                 WHERE email = :email
                   AND tier = :tier
                   AND status IN ('pending', 'retry')
                   AND next_attempt_at <= now()
                 ORDER BY created_at
                 FOR UPDATE SKIP LOCKED
                 LIMIT :limit
                """
            ),
            {"email": first["email"], "tier": first["tier"], "limit": max_rows},
        ).mappings().all()
        row_ids = tuple(row["id"] for row in rows)
        if not row_ids:
            return None
        update = text(
            """
            UPDATE email_outbox
               SET status = 'processing',
                   attempt_count = attempt_count + 1,
                   lease_id = :lease_id,
                   lease_until = now() + interval '5 minutes',
                   updated_at = now()
             WHERE id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True))
        connection.execute(update, {"lease_id": lease_id, "ids": list(row_ids)})
        body_lines = list(dict.fromkeys(str(row["body"]).strip() for row in rows))
        subject = body_lines[0] if len(body_lines) == 1 else f"网球空场提醒（{len(body_lines)} 条）"
        body = "\n".join(body_lines)
        return EmailDigestClaim(
            lease_id=lease_id,
            row_ids=row_ids,
            email=str(first["email"]),
            tier=str(first["tier"]),
            subject=subject,
            body=body,
        )


def _counter_key(email: str) -> str:
    return "email:" + hashlib.sha256(email.encode("utf-8")).hexdigest()


def reserve_daily_delivery(
    claim: EmailDigestClaim,
    settings: NotificationCoreSettings | None = None,
) -> tuple[bool, str]:
    resolved = settings or load_settings()
    delivery_day = (_utcnow() + timedelta(hours=8)).date()
    per_user_limit = (
        resolved.priority_daily_email_limit
        if claim.tier == "priority"
        else resolved.standard_daily_email_limit
    )
    counters = (("global", resolved.global_daily_email_limit), (_counter_key(claim.email), per_user_limit))
    with transaction(resolved) as connection:
        for key, _limit in counters:
            connection.execute(
                text(
                    """
                    INSERT INTO daily_delivery_counters(delivery_day, counter_key)
                    VALUES (:day, :key)
                    ON CONFLICT (delivery_day, counter_key) DO NOTHING
                    """
                ),
                {"day": delivery_day, "key": key},
            )
        rows = connection.execute(
            text(
                """
                SELECT counter_key, reserved_count, submitted_count
                  FROM daily_delivery_counters
                 WHERE delivery_day = :day AND counter_key IN :keys
                 ORDER BY counter_key
                 FOR UPDATE
                """
            ).bindparams(bindparam("keys", expanding=True)),
            {"day": delivery_day, "keys": [key for key, _ in counters]},
        ).mappings().all()
        values = {row["counter_key"]: row for row in rows}
        for key, limit in counters:
            row = values[key]
            if int(row["reserved_count"]) + int(row["submitted_count"]) >= limit:
                return False, f"daily_limit:{key}:{limit}"
        connection.execute(
            text(
                """
                UPDATE daily_delivery_counters
                   SET reserved_count = reserved_count + 1, updated_at = now()
                 WHERE delivery_day = :day AND counter_key IN :keys
                """
            ).bindparams(bindparam("keys", expanding=True)),
            {"day": delivery_day, "keys": [key for key, _ in counters]},
        )
    return True, "reserved"


def finish_daily_reservation(
    claim: EmailDigestClaim,
    *,
    submitted: bool,
    settings: NotificationCoreSettings | None = None,
) -> None:
    resolved = settings or load_settings()
    delivery_day = (_utcnow() + timedelta(hours=8)).date()
    keys = ["global", _counter_key(claim.email)]
    with transaction(resolved) as connection:
        connection.execute(
            text(
                """
                UPDATE daily_delivery_counters
                   SET reserved_count = GREATEST(0, reserved_count - 1),
                       submitted_count = submitted_count + :submitted,
                       updated_at = now()
                 WHERE delivery_day = :day AND counter_key IN :keys
                """
            ).bindparams(bindparam("keys", expanding=True)),
            {"submitted": 1 if submitted else 0, "day": delivery_day, "keys": keys},
        )


def mark_claim_suppressed(
    claim: EmailDigestClaim,
    reason: str,
    settings: NotificationCoreSettings | None = None,
) -> None:
    _update_claim_status(claim, "suppressed", reason, settings=settings)


def mark_claim_retry(
    claim: EmailDigestClaim,
    reason: str,
    *,
    definitive: bool,
    settings: NotificationCoreSettings | None = None,
) -> None:
    resolved = settings or load_settings()
    with transaction(resolved) as connection:
        if not definitive:
            status = "uncertain"
            delay = timedelta(0)
        else:
            max_attempt = int(
                connection.execute(
                    text("SELECT MAX(attempt_count) FROM email_outbox WHERE lease_id = :lease_id"),
                    {"lease_id": claim.lease_id},
                ).scalar_one()
                or 1
            )
            status = "failed" if max_attempt >= 5 else "retry"
            delay = timedelta(minutes=min(60, 2 ** max(0, max_attempt - 1)))
        update = text(
            """
            UPDATE email_outbox
               SET status = :status,
                   next_attempt_at = :next_attempt_at,
                   lease_id = NULL,
                   lease_until = NULL,
                   failed_at = CASE WHEN :terminal THEN now() ELSE failed_at END,
                   last_error = :reason,
                   updated_at = now()
             WHERE id IN :ids AND lease_id = :lease_id
            """
        ).bindparams(bindparam("ids", expanding=True))
        connection.execute(
            update,
            {
                "status": status,
                "next_attempt_at": _utcnow() + delay,
                "terminal": status in {"failed", "uncertain"},
                "reason": reason[:500],
                "ids": list(claim.row_ids),
                "lease_id": claim.lease_id,
            },
        )
        if status == "uncertain":
            connection.execute(
                text(
                    """
                    INSERT INTO delivery_incidents(
                        id, channel, severity, dedupe_key, reference_id,
                        summary, detail
                    ) VALUES (
                        :id, 'email', 'error', :dedupe_key, :reference_id,
                        '腾讯云邮件提交结果不确定，已停止自动重放', :detail
                    ) ON CONFLICT DO NOTHING
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "dedupe_key": f"uncertain:{claim.lease_id}",
                    "reference_id": str(claim.lease_id),
                    "detail": reason[:500],
                },
            )


def _update_claim_status(
    claim: EmailDigestClaim,
    status: str,
    reason: str,
    *,
    settings: NotificationCoreSettings | None = None,
) -> None:
    resolved = settings or load_settings()
    update = text(
        """
        UPDATE email_outbox
           SET status = :status,
               lease_id = NULL,
               lease_until = NULL,
               last_error = :reason,
               updated_at = now()
         WHERE id IN :ids AND lease_id = :lease_id
        """
    ).bindparams(bindparam("ids", expanding=True))
    with transaction(resolved) as connection:
        connection.execute(
            update,
            {
                "status": status,
                "reason": reason[:500],
                "ids": list(claim.row_ids),
                "lease_id": claim.lease_id,
            },
        )


def mark_claim_submitted(
    claim: EmailDigestClaim,
    *,
    message_id: str,
    request_id: str | None,
    settings: NotificationCoreSettings | None = None,
) -> None:
    resolved = settings or load_settings()
    update = text(
        """
        UPDATE email_outbox
           SET status = 'submitted',
               provider_message_id = :message_id,
               provider_request_id = :request_id,
               provider_status = 'accepted',
               submitted_at = now(),
               checked_at = NULL,
               lease_id = NULL,
               lease_until = NULL,
               last_error = NULL,
               updated_at = now()
         WHERE id IN :ids AND lease_id = :lease_id
        """
    ).bindparams(bindparam("ids", expanding=True))
    with transaction(resolved) as connection:
        connection.execute(
            update,
            {
                "message_id": message_id,
                "request_id": request_id,
                "ids": list(claim.row_ids),
                "lease_id": claim.lease_id,
            },
        )


def submitted_messages_due(
    settings: NotificationCoreSettings | None = None,
    *,
    limit: int = 10,
) -> list[SubmittedMessage]:
    resolved = settings or load_settings()
    with transaction(resolved) as connection:
        rows = connection.execute(
            text(
                """
                SELECT provider_message_id, MIN(email) AS email,
                       MIN(submitted_at) AS submitted_at,
                       array_agg(id ORDER BY id) AS row_ids
                  FROM email_outbox
                 WHERE status = 'submitted'
                   AND provider_message_id IS NOT NULL
                   AND (checked_at IS NULL OR checked_at < now() - interval '5 minutes')
                 GROUP BY provider_message_id
                 ORDER BY MIN(submitted_at)
                 LIMIT :limit
                """
            ),
            {"limit": min(max(1, int(limit)), 50)},
        ).mappings().all()
    return [
        SubmittedMessage(
            message_id=str(row["provider_message_id"]),
            email=str(row["email"]),
            row_ids=tuple(row["row_ids"]),
            submitted_at=row["submitted_at"],
        )
        for row in rows
    ]


def mark_provider_status(
    message: SubmittedMessage,
    *,
    status: str,
    provider_status: str,
    delivered_at: datetime | None = None,
    error: str | None = None,
    settings: NotificationCoreSettings | None = None,
) -> None:
    resolved = settings or load_settings()
    update = text(
        """
        UPDATE email_outbox
           SET status = :status,
               provider_status = :provider_status,
               checked_at = now(),
               delivered_at = COALESCE(:delivered_at, delivered_at),
               failed_at = CASE WHEN :status = 'failed' THEN now() ELSE failed_at END,
               last_error = :error,
               updated_at = now()
         WHERE id IN :ids AND provider_message_id = :message_id
        """
    ).bindparams(bindparam("ids", expanding=True))
    with transaction(resolved) as connection:
        connection.execute(
            update,
            {
                "status": status,
                "provider_status": provider_status[:120],
                "delivered_at": delivered_at,
                "error": error[:500] if error else None,
                "ids": list(message.row_ids),
                "message_id": message.message_id,
            },
        )
        if status == "delivered":
            connection.execute(
                text(
                    """
                    UPDATE venue_status v
                       SET last_notification_at = COALESCE(:delivered_at, now()),
                           updated_at = now()
                     WHERE EXISTS (
                         SELECT 1 FROM email_outbox o
                          WHERE o.id IN :ids AND o.venue_id = v.venue_id
                     )
                    """
                ).bindparams(bindparam("ids", expanding=True)),
                {"delivered_at": delivered_at, "ids": list(message.row_ids)},
            )


def service_metrics(
    settings: NotificationCoreSettings | None = None,
) -> dict[str, object]:
    resolved = settings or load_settings()
    with transaction(resolved) as connection:
        state = connection.execute(
            text(
                "SELECT revision, ready, source_count, synced_at, last_error "
                "FROM subscription_snapshot_state WHERE singleton = TRUE"
            )
        ).mappings().one()
        counts = connection.execute(
            text(
                """
                SELECT status, COUNT(*) AS count
                  FROM email_outbox
                 GROUP BY status
                """
            )
        ).mappings().all()
        venues = connection.execute(
            text(
                """
                SELECT venue_id, venue_name, healthy, last_inspection_at,
                       last_notification_at
                  FROM venue_status
                 ORDER BY venue_name, venue_id
                """
            )
        ).mappings().all()
    return {
        "subscriptionSnapshot": {
            "revision": state["revision"],
            "ready": bool(state["ready"]),
            "sourceCount": int(state["source_count"] or 0),
            "syncedAt": state["synced_at"].isoformat() if state["synced_at"] else None,
            "hasError": bool(state["last_error"]),
        },
        "emailOutbox": {str(row["status"]): int(row["count"]) for row in counts},
        "venues": [
            {
                "id": row["venue_id"],
                "name": row["venue_name"],
                "healthy": bool(row["healthy"]),
                "lastInspectionAt": row["last_inspection_at"].isoformat(),
                "lastNotificationAt": (
                    row["last_notification_at"].isoformat()
                    if row["last_notification_at"]
                    else None
                ),
            }
            for row in venues
        ],
    }
