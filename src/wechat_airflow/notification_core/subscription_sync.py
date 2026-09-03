from __future__ import annotations

from typing import Any, Mapping

import requests

from wechat_airflow.notification_core.config import NotificationCoreSettings
from wechat_airflow.notification_core.repository import (
    record_snapshot_error,
    synchronize_subscription_snapshot,
)


class SubscriptionSnapshotError(RuntimeError):
    pass


def fetch_subscription_snapshot(
    settings: NotificationCoreSettings,
) -> Mapping[str, Any]:
    if not settings.subscription_snapshot_url:
        raise SubscriptionSnapshotError("subscription snapshot URL is not configured")
    if not settings.subscription_snapshot_token:
        raise SubscriptionSnapshotError("subscription snapshot token is not configured")
    try:
        response = requests.get(
            settings.subscription_snapshot_url,
            headers={
                "Authorization": f"Bearer {settings.subscription_snapshot_token}",
                "Accept": "application/json",
            },
            timeout=(5, 20),
        )
    except requests.RequestException as exc:
        raise SubscriptionSnapshotError(
            f"snapshot request failed: {type(exc).__name__}"
        ) from exc
    if response.status_code != 200:
        raise SubscriptionSnapshotError(
            f"snapshot endpoint returned HTTP {response.status_code}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise SubscriptionSnapshotError("snapshot endpoint returned invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise SubscriptionSnapshotError("snapshot response must be an object")
    return payload


def synchronize_from_cloudflare(
    settings: NotificationCoreSettings,
) -> dict[str, object]:
    try:
        payload = fetch_subscription_snapshot(settings)
        return synchronize_subscription_snapshot(payload, settings)
    except Exception as exc:
        record_snapshot_error(f"{type(exc).__name__}: {str(exc)[:400]}", settings)
        raise
