from __future__ import annotations

from typing import Any, Mapping, Sequence

import requests

from wechat_airflow.notification_core.config import NotificationCoreSettings
from wechat_airflow.notification_core.repository import service_metrics


class VenueStatusMirrorError(RuntimeError):
    pass


def mirror_venue_status(settings: NotificationCoreSettings) -> dict[str, int]:
    """Best-effort presentation mirror.

    Cloudflare receives only sanitized venue health/timestamps. No subscription,
    recipient, outbox, matching, or delivery decision crosses this boundary.
    """
    if not settings.venue_status_mirror_url:
        return {"venuesAccepted": 0}
    if not settings.subscription_snapshot_token:
        raise VenueStatusMirrorError("venue mirror token is not configured")
    metrics = service_metrics(settings)
    venues = metrics.get("venues")
    if not isinstance(venues, Sequence):
        venues = []
    payload = {
        "generatedAt": metrics.get("generatedAt"),
        "venues": list(venues),
    }
    try:
        response = requests.post(
            settings.venue_status_mirror_url,
            headers={
                "Authorization": f"Bearer {settings.subscription_snapshot_token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(5, 15),
        )
    except requests.RequestException as exc:
        raise VenueStatusMirrorError(
            f"venue mirror request failed: {type(exc).__name__}"
        ) from exc
    if response.status_code != 200:
        raise VenueStatusMirrorError(
            f"venue mirror returned HTTP {response.status_code}"
        )
    try:
        result: Any = response.json()
    except ValueError as exc:
        raise VenueStatusMirrorError("venue mirror returned invalid JSON") from exc
    if not isinstance(result, Mapping) or result.get("success") is not True:
        raise VenueStatusMirrorError("venue mirror rejected the snapshot")
    return {"venuesAccepted": int(result.get("venuesAccepted") or 0)}
