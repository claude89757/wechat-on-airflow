from __future__ import annotations

from datetime import date

import pytest

from wechat_airflow.host_core.domain import (
    IDEAL_WINDOWS,
    SUBSCRIBER_DIGEST_NOTE,
    SlotObservation,
    decrypt_invite_code,
    describe_preference,
    encrypt_invite_code,
    generate_invite_code,
    hash_invite_code,
    normalize_invite_code,
    observation_fingerprint,
    resolve_subscription_window,
    resolve_term,
    slot_matches,
    validate_observation,
    validate_subscription,
    weekday_mask,
    with_subscriber_digest_note,
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


def test_named_ideal_window_maps_onto_the_existing_single_window() -> None:
    window = resolve_subscription_window({"preferencePreset": "weekend_morning"})
    assert window == ((6, 7), "08:00", "12:00")
    created = validate_subscription(
        {
            "venueIds": ["tops"],
            "preferencePreset": "weekday_evening",
            "weekdays": [1, 2, 3, 4, 5],
            "startTime": "19:00",
            "endTime": "22:00",
            "termCode": "7d",
        },
        priority=False,
    )
    assert created.weekdays == (1, 2, 3, 4, 5)
    assert (created.start_time, created.end_time) == ("19:00", "22:00")
    assert describe_preference(created.weekdays, created.start_time, created.end_time) == (
        "weekday_evening",
        "下班后打球",
    )


def test_legacy_subscription_without_a_preset_stays_custom() -> None:
    created = validate_subscription(
        {
            "venueIds": ["tops", "szw"],
            "startTime": "18:00",
            "endTime": "22:00",
            "termCode": "7d",
        },
        priority=False,
    )
    assert created.weekdays == (1, 2, 3, 4, 5, 6, 7)
    assert describe_preference(created.weekdays, created.start_time, created.end_time) == (
        "custom",
        "自定义",
    )


def test_preset_rejects_a_conflicting_clock_or_unknown_id() -> None:
    with pytest.raises(ValueError, match="不一致"):
        resolve_subscription_window(
            {
                "preferencePreset": "weekday_evening",
                "weekdays": [6, 7],
                "startTime": "08:00",
                "endTime": "12:00",
            }
        )
    with pytest.raises(ValueError, match="预设无效"):
        resolve_subscription_window({"preferencePreset": "all_day"})


def test_ideal_windows_drop_email_slots_outside_the_preset() -> None:
    inside = {
        "weekday_evening": SlotObservation(date(2026, 9, 7), "1号场", "19:30", "20:30"),
        "weekday_noon": SlotObservation(date(2026, 9, 7), "1号场", "12:00", "13:00"),
        "weekend_morning": SlotObservation(date(2026, 9, 5), "1号场", "08:30", "09:30"),
        "weekend_afternoon": SlotObservation(date(2026, 9, 5), "1号场", "15:00", "16:00"),
    }
    monday_morning = SlotObservation(date(2026, 9, 7), "1号场", "09:00", "10:00")
    for window in IDEAL_WINDOWS:
        mask = weekday_mask(window.weekdays)
        assert slot_matches(
            inside[window.preset_id],
            weekday_mask_value=mask,
            start_time=window.start_time,
            end_time=window.end_time,
        )
        assert not slot_matches(
            monday_morning,
            weekday_mask_value=mask,
            start_time=window.start_time,
            end_time=window.end_time,
        )


def test_digest_note_does_not_become_another_slot_line() -> None:
    body = with_subscriber_digest_note("TOPS 1号场 09-07 星期一 19:30-20:30")
    assert body.endswith(SUBSCRIBER_DIGEST_NOTE)
    assert with_subscriber_digest_note(body) == body
    assert body.splitlines()[0].count("19:30-20:30") == 1


def test_subscriber_digest_note_is_applied_after_slot_lines() -> None:
    import inspect

    from wechat_airflow.host_core.worker import _attempt_email

    source = inspect.getsource(_attempt_email)
    assert source.index("format_digest") < source.index("with_subscriber_digest_note")


def test_wechat_admission_ignores_personal_windows() -> None:
    import inspect

    from wechat_airflow.host_core.service import active_subscription_for_venue

    source = inspect.getsource(active_subscription_for_venue)
    assert "start_time" not in source
    assert "end_time" not in source
    assert "weekday_mask" not in source


def test_slot_matching_uses_booking_date_weekday_and_overlap() -> None:
    slot = SlotObservation(date(2026, 9, 4), "1号场", "18:30", "20:00")
    mask = weekday_mask([5])
    assert slot_matches(slot, weekday_mask_value=mask, start_time="19:00", end_time="21:00")
    assert not slot_matches(
        slot, weekday_mask_value=weekday_mask([4]), start_time="19:00", end_time="21:00"
    )
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
    assert (
        term.active_until - term.active_until.replace(hour=0, minute=0, second=0, microsecond=0)
    ).days >= 0
