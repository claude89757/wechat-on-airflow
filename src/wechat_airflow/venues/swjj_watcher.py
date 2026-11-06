"""深湾竞界网匹中心巡检 — 银豹/PosPal 场地预约。"""

from __future__ import annotations

from wechat_airflow.venues.pospal_venue import SWJJ, run_check


def run_check_tennis_courts() -> None:
    run_check(SWJJ)
