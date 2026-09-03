from __future__ import annotations

from wechat_airflow.notification_core.subscription_sync import snapshot_request_url


def test_regular_snapshot_url_does_not_export_event_history() -> None:
    assert snapshot_request_url(
        "https://zacks.example/api/internal/subscription-snapshot?includeEvents=1",
        include_events=False,
    ) == "https://zacks.example/api/internal/subscription-snapshot"


def test_cutover_snapshot_url_explicitly_exports_event_history() -> None:
    assert snapshot_request_url(
        "https://zacks.example/api/internal/subscription-snapshot",
        include_events=True,
    ) == "https://zacks.example/api/internal/subscription-snapshot?includeEvents=1"
