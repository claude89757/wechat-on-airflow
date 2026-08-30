from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_web_venue_cadence_labels_match_the_airflow_policy() -> None:
    policy = yaml.safe_load((ROOT / "config/venue-schedule-policy.yaml").read_text())
    source = (ROOT / "webapp/src/venue-inspection-display.ts").read_text()

    assert f"DEFAULT_INSPECTION_CADENCE_SECONDS = {policy['default_interval_seconds']}" in source

    exception_ids = {
        "深圳湾网球场巡检": "szw",
        "大沙河国际网球中心巡检": "dsh",
    }
    for dag_id, venue_id in exception_ids.items():
        interval = policy["exceptions"][dag_id]["interval_seconds"]
        assert f"{venue_id}: {interval}" in source


def test_web_labels_status_sync_without_adding_an_api_path() -> None:
    prototype = (ROOT / "webapp/src/Prototype.tsx").read_text()
    helper = (ROOT / "webapp/src/venue-inspection-display.ts").read_text()

    assert 'from "./venue-inspection-display"' in prototype
    assert "状态同步${compactRelative}" in prototype
    assert "巡检与页面同步分开" in prototype
    assert "页面每 30 秒更新" in prototype
    assert "fetch(" not in helper
    assert "/api/" not in helper
