from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy import text

from wechat_airflow.notification_core.config import NotificationCoreSettings
from wechat_airflow.notification_core.database import transaction


def apply_imported_event_barrier(
    payload: object,
    settings: NotificationCoreSettings,
) -> dict[str, int]:
    if not isinstance(payload, Mapping):
        raise ValueError("snapshot payload must be an object")
    raw_events = payload.get("subscriptionEvents") or payload.get("events") or []
    if not isinstance(raw_events, Sequence) or isinstance(
        raw_events, (str, bytes, bytearray)
    ):
        raise ValueError("snapshot events must be an array")

    imported = 0
    with transaction(settings) as connection:
        for item in raw_events:
            if not isinstance(item, Mapping):
                continue
            subscription_id = str(
                item.get("subscriptionId") or item.get("subscription_id") or ""
            ).strip()
            event_key = str(item.get("eventKey") or item.get("event_key") or "").strip()
            if not subscription_id or not event_key:
                continue
            result = connection.execute(
                text(
                    """
                    UPDATE subscription_events
                       SET imported = TRUE
                     WHERE subscription_id = :subscription_id
                       AND event_key = :event_key
                    """
                ),
                {"subscription_id": subscription_id, "event_key": event_key},
            )
            imported += int(result.rowcount or 0)
        suppressed = connection.execute(
            text(
                """
                UPDATE email_outbox outbox
                   SET status = 'suppressed',
                       last_error = 'pre-cutover event already owned by D1',
                       updated_at = now()
                 WHERE outbox.status IN ('pending', 'retry')
                   AND EXISTS (
                       SELECT 1
                         FROM subscription_events events
                        WHERE events.subscription_id = outbox.subscription_id
                          AND events.event_key = outbox.event_key
                          AND events.imported = TRUE
                   )
                """
            )
        )
    return {"importedEventsMarked": imported, "localRowsSuppressed": int(suppressed.rowcount or 0)}
