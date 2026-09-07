#!/usr/bin/env python3
from __future__ import annotations

from wechat_airflow.venues.pospal_slots import directly_bookable_slots


def _slot(
    court: str,
    uid: str,
    begin: str,
    end: str,
    *,
    can_book: bool = True,
) -> dict[str, object]:
    return {
        "classRoomName": court,
        "txtClassroomUid": uid,
        "beginDatetime": begin,
        "endDatetime": end,
        "apptInfo": {"canApptOrNot": can_book},
    }


def test_directly_bookable_slots_subtracts_enrollment_overlay_by_overlap() -> None:
    response = {
        "result": {
            "slots": [
                _slot("5号风雨场", "5", "2026-09-07 18:00:00", "2026-09-07 18:59:00"),
                _slot("5号风雨场", "5", "2026-09-07 19:00:00", "2026-09-07 19:59:00"),
                _slot("6号风雨场", "6", "2026-09-07 18:00:00", "2026-09-07 18:59:00"),
            ],
            "enrollSlots": [
                {
                    "classRoomName": "5号风雨场",
                    "txtClassroomUid": "5",
                    "beginDatetime": "2026-09-07 18:00:00",
                    "endDatetime": "2026-09-07 19:59:00",
                    "capacity": 0,
                    "status": 0,
                }
            ],
        }
    }

    result = directly_bookable_slots(response)

    assert [(slot["classRoomName"], slot["beginDatetime"]) for slot in result] == [
        ("6号风雨场", "2026-09-07 18:00:00")
    ]


def test_directly_bookable_slots_preserves_normal_direct_inventory() -> None:
    response = {
        "result": {
            "slots": [
                _slot("1号场", "1", "2026-09-08 18:00:00", "2026-09-08 18:59:00"),
                _slot(
                    "2号场",
                    "2",
                    "2026-09-08 18:00:00",
                    "2026-09-08 18:59:00",
                    can_book=False,
                ),
            ],
            "enrollSlots": [],
        }
    }

    result = directly_bookable_slots(response)

    assert len(result) == 1
    assert result[0]["classRoomName"] == "1号场"


def test_malformed_enrollment_overlay_does_not_hide_valid_inventory() -> None:
    response = {
        "result": {
            "slots": [_slot("1号场", "1", "2026-09-08 18:00:00", "2026-09-08 18:59:00")],
            "enrollSlots": [
                {
                    "classRoomName": "1号场",
                    "txtClassroomUid": "1",
                    "beginDatetime": "bad-time",
                    "endDatetime": "bad-time",
                }
            ],
        }
    }

    assert len(directly_bookable_slots(response)) == 1
