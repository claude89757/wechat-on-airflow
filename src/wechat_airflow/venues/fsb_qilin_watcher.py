"""泛思博特麒麟网球场巡检 — 银豹/PosPal 场地预约。"""

from __future__ import annotations

from wechat_airflow.venues.pospal_venue import FSB_QILIN, run_check


def run_check_tennis_courts() -> None:
    run_check(FSB_QILIN)
