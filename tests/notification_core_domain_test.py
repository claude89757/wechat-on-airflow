from __future__ import annotations

from datetime import date

import pytest

from wechat_airflow.notification_core.domain import (
    NormalizedSlot,
    event_key_for,
    normalize_observation,
    normalize_subscription,
    slot_matches_subscription,
)


def test_observation_identity_ignores_slot_order_and_timestamp() -> None:
    first = normalize_observation(
        {
            "venue_id": "tops",
            "venue_name": "TOPS 科技园",
            "healthy": True,
            "checked_at": "2026-09-03T10:00:00+08:00",
            "slots": [
                {
                    "date": "2026-09-04",
                    "court_name": "1号场",
                    "start_time": "18:00",
                    "end_time": "19:00",
                },
                {
                    "date": "2026-09-04",
                    "court_name": "2号场",
                    "start_time": "19:00",
                    "end_time": "20:00",
                },
            ],
        }
    )
    second = normalize_observation(
        {
            "venueId": "tops",
            "venueName": "TOPS 科技园",
            "healthy": True,
            "checkedAt": "2026-09-03T10:01:00+08:00",
            "slots": list(reversed([
                {
                    "date": "2026-09-04",
                    "court_name": "1号场",
                    "start_time": "18:00",
                    "end_time": "19:00",
                },
                {
                    "date": "2026-09-04",
                    "court_name": "2号场",
                    "start_time": "19:00",
                    "end_time": "20:00",
                },
            ])),
        }
    )
    assert first.fingerprint == second.fingerprint


def test_event_key_includes_venue() -> None:
    slot = NormalizedSlot(date(2026, 9, 4), "1号场", 18 * 60, 19 * 60)
    assert event_key_for("tops", slot) != event_key_for("szw", slot)


def test_subscription_normalization_and_overlap() -> None:
    subscription = normalize_subscription(
        {
            "id": "sub-1",
            "email": "USER@example.com",
            "venueIds": ["tops"],
            "weekdays": [5],
            "startTime": "18:00",
            "endTime": "22:00",
            "tier": "priority",
            "autoRenew": True,
            "activeUntil": "2026-12-01T00:00:00+08:00",
            "updatedAt": "2026-09-03T10:00:00+08:00",
        }
    )
    assert subscription.email == "user@example.com"
    assert subscription.weekday_mask == 1 << 4
    assert slot_matches_subscription(
        NormalizedSlot(date(2026, 9, 4), "1号场", 19 * 60, 20 * 60),
        weekday_mask=subscription.weekday_mask,
        start_minute=subscription.start_minute,
        end_minute=subscription.end_minute,
    )
    assert not slot_matches_subscription(
        NormalizedSlot(date(2026, 9, 5), "1号场", 19 * 60, 20 * 60),
        weekday_mask=subscription.weekday_mask,
        start_minute=subscription.start_minute,
        end_minute=subscription.end_minute,
    )


def test_invalid_time_range_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_subscription(
            {
                "id": "sub-1",
                "email": "user@example.com",
                "venueIds": ["tops"],
                "weekdays": [1],
                "startTime": "20:00",
                "endTime": "19:00",
                "activeUntil": "2026-12-01T00:00:00+08:00",
                "updatedAt": "2026-09-03T10:00:00+08:00",
            }
        )
