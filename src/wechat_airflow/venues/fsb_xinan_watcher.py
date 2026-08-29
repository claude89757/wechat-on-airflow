"""泛思博特新安网球场巡检 — 银豹/PosPal 场地预约。"""

from __future__ import annotations

from wechat_airflow.venues.pospal_venue import FSB_XINAN, run_check


def run_check_tennis_courts() -> None:
    run_check(FSB_XINAN)
