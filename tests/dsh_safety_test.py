from __future__ import annotations

import pytest

from wechat_airflow.venues.dsh_safety import reject_implausible_full_day


def test_rejects_screenshot_pattern_eight_courts_full_day() -> None:
    courts = {f"网球场{i}": [["08:00", "22:30"]] for i in range(1, 9)}
    with pytest.raises(ValueError, match="implausible_full_day_availability"):
        reject_implausible_full_day(courts)


def test_rejects_split_cells_after_merge() -> None:
    flattened: list[list[str]] = []
    for hour in range(8, 22):
        flattened.extend(
            [[f"{hour:02d}:00", f"{hour:02d}:30"], [f"{hour:02d}:30", f"{hour + 1:02d}:00"]]
        )
    courts = {f"网球场{i}": flattened for i in range(1, 7)}
    with pytest.raises(ValueError, match="implausible_full_day_availability"):
        reject_implausible_full_day(courts)


def test_keeps_normal_concentrated_release() -> None:
    courts = {f"网球场{i}": [["18:00", "22:00"]] for i in range(1, 9)}
    assert reject_implausible_full_day(courts) == courts


def test_keeps_one_long_row_without_venue_wide_pattern() -> None:
    courts = {"网球场1": [["08:00", "22:30"]], "网球场2": [["18:00", "20:00"]]}
    assert reject_implausible_full_day(courts) == courts
