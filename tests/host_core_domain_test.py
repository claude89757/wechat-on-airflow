from __future__ import annotations

from datetime import date

import pytest

from wechat_airflow.host_core.domain import (
    SlotObservation,
    decrypt_invite_code,
    encrypt_invite_code,
    generate_invite_code,
    hash_invite_code,
    normalize_invite_code,
    observation_fingerprint,
    resolve_term,
    slot_matches,
    validate_observation,
    validate_subscription,
    weekday_mask,
)


def test_observation_fingerprint_ignores_poll_timestamp_and_slot_order() -> None:
    left = validate_observation(
        {
            "venue_id": "tops",
            "venue_name": "TOPS 科技园",
            "observation_scope": "day-1",
            "healthy": True,
            "checked_at": "2026-09-03T00:00:00Z",
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
    right = validate_observation(
        {
            "venue_id": "tops",
            "venue_name": "TOPS 科技园",
            "observation_scope": "day-1",
            "healthy": True,
            "checked_at": "2026-09-03T00:01:00Z",
            "slots": list(reversed([slot.as_public_dict() for slot in left.slots])),
        }
    )
    assert observation_fingerprint(left) == observation_fingerprint(right)


def test_subscription_validation_keeps_priority_terms_out_of_standard_tier() -> None:
    payload = {
        "venueIds": ["tops"],
        "weekdays": [1, 3, 5],
        "startTime": "18:00",
        "endTime": "22:00",
        "termCode": "90d",
    }
    with pytest.raises(ValueError, match="优先用户"):
        validate_subscription(payload, priority=False)
    assert validate_subscription(payload, priority=True).term_code == "90d"


def test_slot_matching_uses_booking_date_weekday_and_overlap() -> None:
    slot = SlotObservation(date(2026, 9, 4), "1号场", "18:30", "20:00")
    mask = weekday_mask([5])
    assert slot_matches(slot, weekday_mask_value=mask, start_time="19:00", end_time="21:00")
    assert not slot_matches(slot, weekday_mask_value=weekday_mask([4]), start_time="19:00", end_time="21:00")
    assert not slot_matches(slot, weekday_mask_value=mask, start_time="20:00", end_time="21:00")


def test_invite_codes_round_trip_under_host_owned_secret() -> None:
    code = generate_invite_code()
    normalized = normalize_invite_code(code.lower())
    ciphertext = encrypt_invite_code(normalized, "test-pepper")
    assert decrypt_invite_code(ciphertext, "test-pepper") == normalized
    assert decrypt_invite_code(ciphertext, "other-pepper") is None
    assert hash_invite_code(normalized, "test-pepper") == hash_invite_code(code, "test-pepper")


def test_long_term_subscription_uses_renewable_lease() -> None:
    term = resolve_term("long_term")
    assert term.auto_renew is True
    assert term.duration_days == 0
    assert (term.active_until - term.active_until.replace(hour=0, minute=0, second=0, microsecond=0)).days >= 0
