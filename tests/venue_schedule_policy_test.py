from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, cast
from unittest import TestCase

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import check_active_components  # noqa: E402

MANIFEST_PATH = ROOT / "config" / "active-components.yaml"
POLICY_PATH = ROOT / "config" / "venue-schedule-policy.yaml"
EXPECTED_EXCEPTIONS = {
    "深圳湾网球场巡检": "every_15_seconds",
    "大沙河国际网球中心巡检": "every_3_minutes",
}


def load_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AssertionError(f"{path.relative_to(ROOT)} must contain a mapping")
    return cast(dict[str, Any], value)


class VenueSchedulePolicyTest(TestCase):
    def test_active_venue_dags_follow_the_one_minute_default(self) -> None:
        manifest = load_mapping(MANIFEST_PATH)
        policy = load_mapping(POLICY_PATH)

        self.assertEqual(policy.get("schema_version"), 1)
        self.assertEqual(policy.get("default_schedule"), "every_1_minutes")
        self.assertEqual(policy.get("default_interval_seconds"), 60)
        self.assertTrue(policy.get("change_control", {}).get("new_venues_use_default"))

        scope = cast(dict[str, Any], policy.get("scope") or {})
        path_prefix = str(scope.get("dag_path_prefix") or "")
        self.assertEqual(path_prefix, "dags/tennis_dags/sz_tennis/")

        exceptions = cast(dict[str, dict[str, Any]], policy.get("exceptions") or {})
        exception_schedules = {
            dag_id: str(config.get("schedule") or "")
            for dag_id, config in exceptions.items()
        }
        self.assertEqual(exception_schedules, EXPECTED_EXCEPTIONS)
        for config in exceptions.values():
            self.assertTrue(str(config.get("reason") or "").strip())

        active_dags = cast(list[dict[str, Any]], manifest.get("active_dags") or [])
        venue_dags = {
            str(component.get("dag_id") or ""): component
            for component in active_dags
            if str(component.get("file") or "").startswith(path_prefix)
        }
        self.assertGreater(len(venue_dags), len(EXPECTED_EXCEPTIONS))
        self.assertTrue(set(EXPECTED_EXCEPTIONS).issubset(venue_dags))

        for dag_id, component in venue_dags.items():
            expected_schedule = exception_schedules.get(
                dag_id,
                str(policy["default_schedule"]),
            )
            relative_file = str(component.get("file") or "")
            self.assertEqual(
                component.get("schedule"),
                expected_schedule,
                f"{dag_id} must follow the declared venue schedule policy",
            )
            self.assertEqual(
                check_active_components.dag_schedule_contract(ROOT / relative_file),
                expected_schedule,
                f"{relative_file} source schedule must match the policy",
            )
