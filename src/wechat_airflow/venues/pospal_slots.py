"""PosPal direct-booking availability guards.

PosPal renders organized enrollment sessions from ``result.enrollSlots`` on
top of ordinary court inventory from ``result.slots``. The underlying
ordinary slot can still report ``apptInfo.canApptOrNot = true`` while the
mini-program visibly assigns that court to an enrollment activity. Such a
slot is not whole-court inventory and must never be published as an empty
court.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True)
class _EnrollmentInterval:
    court_uid: str
    court_name: str
    begin: datetime.datetime
    end_exclusive: datetime.datetime


def _as_mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _clean_text(value: object) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def _court_uid(item: dict[str, object]) -> str:
    return _clean_text(item.get("txtClassroomUid") or item.get("classroomUid"))


def _court_name(item: dict[str, object]) -> str:
    return _clean_text(item.get("classRoomName"))


def _time_range(
    item: dict[str, object],
) -> tuple[datetime.datetime, datetime.datetime] | None:
    begin_raw = item.get("beginDatetime")
    end_raw = item.get("endDatetime")
    if not isinstance(begin_raw, str) or not isinstance(end_raw, str):
        return None
    try:
        begin = datetime.datetime.strptime(begin_raw, DATETIME_FORMAT)
        # PosPal uses inclusive cells such as 18:00:00-18:59:00.
        end_exclusive = datetime.datetime.strptime(
            end_raw, DATETIME_FORMAT
        ) + datetime.timedelta(minutes=1)
    except ValueError:
        return None
    if end_exclusive <= begin:
        return None
    return begin, end_exclusive


def _enrollment_intervals(value: object) -> list[_EnrollmentInterval]:
    if not isinstance(value, list):
        return []
    intervals: list[_EnrollmentInterval] = []
    for raw_item in value:
        item = _as_mapping(raw_item)
        time_range = _time_range(item)
        if time_range is None:
            continue
        court_uid = _court_uid(item)
        court_name = _court_name(item)
        if not court_uid and not court_name:
            continue
        intervals.append(
            _EnrollmentInterval(
                court_uid=court_uid,
                court_name=court_name,
                begin=time_range[0],
                end_exclusive=time_range[1],
            )
        )
    return intervals


def _same_court(slot: dict[str, object], enrollment: _EnrollmentInterval) -> bool:
    slot_uid = _court_uid(slot)
    if slot_uid and enrollment.court_uid:
        return slot_uid == enrollment.court_uid
    slot_name = _court_name(slot)
    return bool(slot_name and enrollment.court_name and slot_name == enrollment.court_name)


def _blocked_by_enrollment(
    slot: dict[str, object], enrollments: list[_EnrollmentInterval]
) -> bool:
    slot_range = _time_range(slot)
    if slot_range is None:
        return False
    slot_begin, slot_end = slot_range
    return any(
        _same_court(slot, enrollment)
        and max(slot_begin, enrollment.begin)
        < min(slot_end, enrollment.end_exclusive)
        for enrollment in enrollments
    )


def directly_bookable_slots(json_data: object) -> list[dict[str, object]]:
    """Return slots genuinely available for whole-court direct booking.

    ``canApptOrNot`` covers the ordinary appointment layer only. Every valid
    interval returned in ``enrollSlots`` is therefore a court blocker,
    irrespective of enrollment capacity or participant count. This prefers
    suppressing a doubtful alert over announcing inventory that the official
    mini-program does not expose as an empty court.
    """

    payload = _as_mapping(json_data)
    result = _as_mapping(payload.get("result"))
    raw_slots = result.get("slots")
    if not isinstance(raw_slots, list):
        return []

    enrollments = _enrollment_intervals(result.get("enrollSlots"))
    available: list[dict[str, object]] = []
    for raw_slot in raw_slots:
        slot = _as_mapping(raw_slot)
        appt_info = _as_mapping(slot.get("apptInfo"))
        if appt_info.get("canApptOrNot") is not True:
            continue
        if _blocked_by_enrollment(slot, enrollments):
            continue
        available.append(slot)
    return available
