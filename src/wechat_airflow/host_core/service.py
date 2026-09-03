from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .database import transaction
from .domain import (
    VenueObservation,
    format_slot_line,
    observation_fingerprint,
    slot_event_key,
    slot_matches,
    utc_now,
    validate_observation,
)


def _active_subscriptions(connection: Connection, venue_id: str) -> list[Mapping[str, Any]]:
    return list(
        connection.execute(
            text(
                """
                SELECT
                    s.id,
                    s.email,
                    s.start_time,
                    s.end_time,
                    s.weekday_mask,
                    CASE
                        WHEN tiers.tier = 'priority' AND tiers.revoked_at IS NULL
                        THEN 'priority'
                        ELSE 'standard'
                    END AS tier
                FROM zacks.subscription_venues selected
                JOIN zacks.subscriptions s ON s.id = selected.subscription_id
                LEFT JOIN zacks.user_delivery_tiers tiers ON tiers.email = s.email
                WHERE selected.venue_id = :venue_id
                  AND s.active = true
                  AND s.active_until > now()
                  AND (
                    s.auto_renew = false
                    OR (tiers.tier = 'priority' AND tiers.revoked_at IS NULL)
                  )
                ORDER BY s.id
                """
            ),
            {"venue_id": venue_id},
        ).mappings()
    )


def active_subscription_for_venue(venue_id: str) -> bool:
    with transaction() as connection:
        return bool(
            connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1
                        FROM zacks.subscription_venues selected
                        JOIN zacks.subscriptions s ON s.id = selected.subscription_id
                        LEFT JOIN zacks.user_delivery_tiers tiers ON tiers.email = s.email
                        WHERE selected.venue_id = :venue_id
                          AND s.active = true
                          AND s.active_until > now()
                          AND (
                            s.auto_renew = false
                            OR (tiers.tier = 'priority' AND tiers.revoked_at IS NULL)
                          )
                    ) AS allowed
                    """
                ),
                {"venue_id": venue_id},
            ).scalar_one()
        )


def _generation(connection: Connection, venue_id: str) -> int:
    value = connection.execute(
        text(
            """
            SELECT generation
            FROM zacks.subscription_generations
            WHERE venue_id = :venue_id
            """
        ),
        {"venue_id": venue_id},
    ).scalar_one_or_none()
    return int(value or 0)


def increment_subscription_generations(connection: Connection, venue_ids: list[str]) -> None:
    now = utc_now()
    for venue_id in sorted(set(venue_ids)):
        connection.execute(
            text(
                """
                INSERT INTO zacks.subscription_generations(venue_id, generation, updated_at)
                VALUES (:venue_id, 1, :updated_at)
                ON CONFLICT (venue_id) DO UPDATE SET
                    generation = zacks.subscription_generations.generation + 1,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {"venue_id": venue_id, "updated_at": now},
        )


def _upsert_status(connection: Connection, observation: VenueObservation, now: datetime) -> None:
    connection.execute(
        text(
            """
            INSERT INTO zacks.venue_status(
                venue_id, venue_name, healthy, last_inspection_at, last_error, updated_at
            )
            VALUES (
                :venue_id, :venue_name, :healthy, :last_inspection_at, :last_error, :updated_at
            )
            ON CONFLICT (venue_id) DO UPDATE SET
                venue_name = EXCLUDED.venue_name,
                healthy = EXCLUDED.healthy,
                last_inspection_at = EXCLUDED.last_inspection_at,
                last_error = EXCLUDED.last_error,
                updated_at = EXCLUDED.updated_at
            """
        ),
        {
            "venue_id": observation.venue_id,
            "venue_name": observation.venue_name,
            "healthy": observation.healthy,
            "last_inspection_at": observation.checked_at,
            "last_error": observation.error,
            "updated_at": now,
        },
    )


def _gate(allowed: bool, now: datetime) -> dict[str, Any]:
    valid_until = now + timedelta(hours=24)
    return {
        "allowed": allowed,
        "source": "airflow-host",
        "evaluatedAt": now.isoformat(),
        "validUntil": valid_until.isoformat(),
        "revision": int(now.timestamp() * 1_000),
    }


def ingest_observation(payload: object) -> dict[str, Any]:
    observation = validate_observation(payload)
    fingerprint = observation_fingerprint(observation)
    observation_key = f"{observation.venue_id}:{observation.observation_scope}"
    now = utc_now()

    with transaction() as connection:
        _upsert_status(connection, observation, now)
        generation = _generation(connection, observation.venue_id)
        state = connection.execute(
            text(
                """
                SELECT fingerprint, subscription_generation
                FROM zacks.observation_state
                WHERE observation_key = :observation_key
                FOR UPDATE
                """
            ),
            {"observation_key": observation_key},
        ).mappings().first()
        unchanged = bool(
            state
            and state["fingerprint"] == fingerprint
            and int(state["subscription_generation"] or 0) == generation
        )
        subscriptions = _active_subscriptions(connection, observation.venue_id)

        if unchanged:
            connection.execute(
                text(
                    """
                    UPDATE zacks.observation_state
                    SET last_seen_at = :last_seen_at, updated_at = :updated_at
                    WHERE observation_key = :observation_key
                    """
                ),
                {
                    "last_seen_at": observation.checked_at,
                    "updated_at": now,
                    "observation_key": observation_key,
                },
            )
            return {
                "success": True,
                "venueId": observation.venue_id,
                "slotsAccepted": len(observation.slots),
                "matchedNotifications": 0,
                "deduplicated": True,
                "wechatGate": _gate(bool(subscriptions), now),
            }

        matched_notifications = 0
        if observation.healthy:
            for slot in observation.slots:
                event_key = slot_event_key(observation.venue_id, slot)
                connection.execute(
                    text(
                        """
                        INSERT INTO zacks.observed_slots(
                            event_key, venue_id, court_name, booking_date, start_time, end_time,
                            first_observed_at, last_observed_at
                        )
                        VALUES (
                            :event_key, :venue_id, :court_name, :booking_date, :start_time,
                            :end_time, :observed_at, :observed_at
                        )
                        ON CONFLICT (event_key) DO UPDATE SET
                            last_observed_at = EXCLUDED.last_observed_at
                        """
                    ),
                    {
                        "event_key": event_key,
                        "venue_id": observation.venue_id,
                        "court_name": slot.court_name,
                        "booking_date": slot.booking_date,
                        "start_time": slot.start_time,
                        "end_time": slot.end_time,
                        "observed_at": now,
                    },
                )
                for subscription in subscriptions:
                    if not slot_matches(
                        slot,
                        weekday_mask_value=int(subscription["weekday_mask"]),
                        start_time=str(subscription["start_time"]),
                        end_time=str(subscription["end_time"]),
                    ):
                        continue
                    inserted = connection.execute(
                        text(
                            """
                            INSERT INTO zacks.subscription_events(
                                subscription_id, event_key, created_at
                            )
                            VALUES (:subscription_id, :event_key, :created_at)
                            ON CONFLICT (subscription_id, event_key) DO NOTHING
                            RETURNING subscription_id
                            """
                        ),
                        {
                            "subscription_id": subscription["id"],
                            "event_key": event_key,
                            "created_at": now,
                        },
                    ).scalar_one_or_none()
                    if not inserted:
                        continue
                    line = format_slot_line(observation.venue_name, slot)
                    connection.execute(
                        text(
                            """
                            INSERT INTO zacks.notification_outbox(
                                id, subscription_id, event_key, venue_id, email, subject, body,
                                tier, status, attempt_count, next_attempt_at, created_at, updated_at
                            )
                            VALUES (
                                :id, :subscription_id, :event_key, :venue_id, :email, :subject,
                                :body, :tier, 'pending', 0, :next_attempt_at, :created_at, :updated_at
                            )
                            ON CONFLICT (subscription_id, event_key) DO NOTHING
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "subscription_id": subscription["id"],
                            "event_key": event_key,
                            "venue_id": observation.venue_id,
                            "email": subscription["email"],
                            "subject": line,
                            "body": line,
                            "tier": subscription["tier"],
                            "next_attempt_at": now,
                            "created_at": now,
                            "updated_at": now,
                        },
                    )
                    matched_notifications += 1
                    if matched_notifications >= 500:
                        break
                if matched_notifications >= 500:
                    break

        connection.execute(
            text(
                """
                INSERT INTO zacks.observation_state(
                    observation_key, venue_id, fingerprint, subscription_generation,
                    last_seen_at, last_matched_at, updated_at
                )
                VALUES (
                    :observation_key, :venue_id, :fingerprint, :generation,
                    :last_seen_at, :last_matched_at, :updated_at
                )
                ON CONFLICT (observation_key) DO UPDATE SET
                    venue_id = EXCLUDED.venue_id,
                    fingerprint = EXCLUDED.fingerprint,
                    subscription_generation = EXCLUDED.subscription_generation,
                    last_seen_at = EXCLUDED.last_seen_at,
                    last_matched_at = EXCLUDED.last_matched_at,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "observation_key": observation_key,
                "venue_id": observation.venue_id,
                "fingerprint": fingerprint,
                "generation": generation,
                "last_seen_at": observation.checked_at,
                "last_matched_at": now,
                "updated_at": now,
            },
        )

    return {
        "success": True,
        "venueId": observation.venue_id,
        "slotsAccepted": len(observation.slots),
        "matchedNotifications": matched_notifications,
        "deduplicated": False,
        "wechatGate": _gate(bool(subscriptions), now),
    }


def record_wechat_incident(
    *,
    source: str,
    receiver: str,
    message: str,
    error: Exception,
    error_code: str | None = None,
) -> None:
    now = utc_now()
    receiver_hash = hashlib.sha256(receiver.encode()).hexdigest()
    message_hash = hashlib.sha256(message.encode()).hexdigest()
    incident_id = hashlib.sha256(
        f"{source}\0{receiver_hash}\0{message_hash}".encode()
    ).hexdigest()
    reason = str(error)[:1_000]
    try:
        with transaction() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO zacks.wechat_delivery_incidents(
                        id, source, receiver_hash, message_hash, error_code, error_message,
                        first_failed_at, last_failed_at, attempt_count
                    )
                    VALUES (
                        :id, :source, :receiver_hash, :message_hash, :error_code, :error_message,
                        :first_failed_at, :last_failed_at, 1
                    )
                    ON CONFLICT (source, receiver_hash, message_hash) DO UPDATE SET
                        error_code = EXCLUDED.error_code,
                        error_message = EXCLUDED.error_message,
                        last_failed_at = EXCLUDED.last_failed_at,
                        attempt_count = zacks.wechat_delivery_incidents.attempt_count + 1,
                        resolved_at = NULL
                    """
                ),
                {
                    "id": incident_id,
                    "source": source[:120],
                    "receiver_hash": receiver_hash,
                    "message_hash": message_hash,
                    "error_code": error_code[:120] if error_code else None,
                    "error_message": reason,
                    "first_failed_at": now,
                    "last_failed_at": now,
                },
            )
    except Exception:
        return


def runtime_heartbeat(component: str, deployment_commit: str, details: Mapping[str, Any]) -> None:
    with transaction() as connection:
        connection.execute(
            text(
                """
                INSERT INTO zacks.runtime_heartbeats(
                    component, deployment_commit, healthy, details, updated_at
                )
                VALUES (
                    :component, :deployment_commit, true, CAST(:details AS jsonb), :updated_at
                )
                ON CONFLICT (component) DO UPDATE SET
                    deployment_commit = EXCLUDED.deployment_commit,
                    healthy = EXCLUDED.healthy,
                    details = EXCLUDED.details,
                    updated_at = EXCLUDED.updated_at
                """
            ),
            {
                "component": component,
                "deployment_commit": deployment_commit,
                "details": json.dumps(dict(details), separators=(",", ":")),
                "updated_at": datetime.now(UTC),
            },
        )
