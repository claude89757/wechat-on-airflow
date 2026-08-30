"""FFTENNIS前海国际网球中心巡检 — 银豹/PosPal 场地预约。"""

from __future__ import annotations

from wechat_airflow.venues.pospal_venue import FFT_QIANHAI, run_check


def run_check_tennis_courts() -> None:
    run_check(FFT_QIANHAI)
