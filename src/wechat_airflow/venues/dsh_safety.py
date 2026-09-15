from __future__ import annotations

from wechat_airflow.venues import dsh_ydmap_watcher as watcher
from wechat_airflow.venues.dsh_ydmap_client import CourtAvailability

MIN_SUSPICIOUS_COURTS = 6
MIN_SUSPICIOUS_MINUTES = 12 * 60
_ORIGINAL_CANONICALIZE = watcher.canonicalize_court_availability


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)


def reject_implausible_full_day(court_data: CourtAvailability) -> CourtAvailability:
    """Fail closed on the known YDMap unhydrated whole-day-grid false positive."""
    suspicious = 0
    for ranges in court_data.values():
        merged = watcher.merge_time_ranges(ranges)
        if any(_minutes(end) - _minutes(start) >= MIN_SUSPICIOUS_MINUTES for start, end in merged):
            suspicious += 1
    if suspicious >= MIN_SUSPICIOUS_COURTS:
        raise ValueError("implausible_full_day_availability")
    return court_data


def canonicalize_court_availability(court_data: CourtAvailability) -> CourtAvailability:
    canonical = _ORIGINAL_CANONICALIZE(court_data)
    return reject_implausible_full_day(canonical)


def run_check_tennis_courts() -> None:
    original = watcher.canonicalize_court_availability
    watcher.canonicalize_court_availability = canonicalize_court_availability
    try:
        watcher.run_check_tennis_courts()
    finally:
        watcher.canonicalize_court_availability = original
