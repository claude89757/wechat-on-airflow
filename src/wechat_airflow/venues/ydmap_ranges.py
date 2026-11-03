"""Shared time-range helpers for YDMap venue availability payloads."""

from __future__ import annotations


def merge_time_ranges(data: list[list[str]]) -> list[list[str]]:
    """Collapse adjacent or overlapping HH:MM ranges into maximal ranges."""

    if not data:
        return data

    def time_to_minutes(time_str: str) -> int:
        return int(time_str[:2]) * 60 + int(time_str[3:])

    data_in_minutes = sorted((time_to_minutes(start), time_to_minutes(end)) for start, end in data)
    merged: list[tuple[int, int]] = []
    start, end = data_in_minutes[0]
    for next_start, next_end in data_in_minutes[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            merged.append((start, end))
            start, end = next_start, next_end
    merged.append((start, end))
    return [
        [f"{item[0] // 60:02d}:{item[0] % 60:02d}", f"{item[1] // 60:02d}:{item[1] % 60:02d}"]
        for item in merged
    ]
