#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
import types
import unittest


class FakeDAG:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def __enter__(self) -> FakeDAG:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class FakePythonOperator:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    def __rshift__(self, other: object) -> object:
        return other


class FakeVariable:
    values: dict[str, object] = {}

    @classmethod
    def get(cls, key: str, default: object = None, deserialize_json: bool = False) -> object:
        return cls.values.get(key, default)

    @classmethod
    def set(
        cls,
        key: str,
        value: object,
        description: str | None = None,
        serialize_json: bool = False,
    ) -> None:
        cls.values[key] = value


def install_import_stubs() -> None:
    airflow_module = types.ModuleType("airflow")
    airflow_sdk_module = types.ModuleType("airflow.sdk")
    airflow_sdk_module.DAG = FakeDAG
    airflow_sdk_module.Variable = FakeVariable
    python_module = types.ModuleType("airflow.providers.standard.operators.python")
    python_module.PythonOperator = FakePythonOperator
    sys.modules.setdefault("airflow", airflow_module)
    sys.modules.setdefault("airflow.sdk", airflow_sdk_module)
    sys.modules.setdefault("airflow.providers", types.ModuleType("airflow.providers"))
    sys.modules.setdefault(
        "airflow.providers.standard", types.ModuleType("airflow.providers.standard")
    )
    sys.modules.setdefault(
        "airflow.providers.standard.operators",
        types.ModuleType("airflow.providers.standard.operators"),
    )
    sys.modules["airflow.providers.standard.operators.python"] = python_module


install_import_stubs()
dsh_client = importlib.import_module("wechat_airflow.venues.dsh_ydmap_client")
dsh_watcher = importlib.import_module("wechat_airflow.venues.dsh_ydmap_watcher")
dsh_watcher.Variable = FakeVariable


class DshYdmapWatcherTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeVariable.values = {
            "PI_DEVICE_SSH": {
                "host": "203.0.113.10",
                "port": 6000,
                "username": "pi-user",
                "password": "secret",
                "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            },
            "SZ_TENNIS_CHATROOMS": "Zacks_网球场",
        }

    def test_config_requires_complete_ssh_fields(self) -> None:
        with self.assertRaises(ValueError):
            dsh_client.PiDeviceConfig.from_value({"host": "203.0.113.10"})

    def test_config_rejects_non_http_scrape_url(self) -> None:
        with self.assertRaises(ValueError):
            dsh_client.PiDeviceConfig.from_value(
                {
                    **FakeVariable.values["PI_DEVICE_SSH"],
                    "scrape_url": "ftp://127.0.0.1/inspect",
                }
            )

    def test_parse_inspect_payload_keeps_available_slots(self) -> None:
        result = dsh_client.parse_inspect_payload(
            {
                "ok": True,
                "captcha": False,
                "days": [
                    {
                        "date": "2026-08-29",
                        "courts": {
                            "1号风雨场": [["22:00", "22:30"], ["18:00", "19:00"]],
                            "": [["10:00", "11:00"]],
                        },
                    }
                ],
            }
        )
        self.assertEqual(
            result,
            {"2026-08-29": {"1号风雨场": [["22:00", "22:30"], ["18:00", "19:00"]]}},
        )

    def test_parse_inspect_payload_rejects_captcha(self) -> None:
        with self.assertRaisesRegex(ValueError, "captcha"):
            dsh_client.parse_inspect_payload({"ok": False, "captcha": True, "days": []})

    def test_filter_slots_uses_weekday_and_weekend_windows(self) -> None:
        weekday = dsh_watcher.filter_court_data_for_notification(
            "2026-08-31",
            {"1号风雨场": [["16:00", "17:00"], ["18:00", "19:00"], ["22:00", "22:30"]]},
        )
        weekend = dsh_watcher.filter_court_data_for_notification(
            "2026-08-30",
            {"2号风雨场": [["14:00", "15:00"], ["16:00", "17:00"]]},
        )
        self.assertEqual(
            weekday,
            [
                {
                    "date": "08-31",
                    "court_name": "大沙河国际网球中心1号风雨场",
                    "free_slot_list": [["18:00", "19:00"]],
                }
            ],
        )
        self.assertEqual(
            weekend,
            [
                {
                    "date": "08-30",
                    "court_name": "大沙河国际网球中心2号风雨场",
                    "free_slot_list": [["16:00", "17:00"]],
                }
            ],
        )

    def test_check_tennis_courts_publishes_webapp_before_wechat(self) -> None:
        expected_msg = "【大沙河国际网球中心1号风雨场】星期日(08-30)空场: 16:00-18:00"
        original_fetch = dsh_watcher.fetch_inspect_payload
        original_publish = dsh_watcher.publish_venue_observation
        original_enqueue = dsh_watcher.enqueue_wechat_message
        original_datetime = dsh_watcher.datetime

        class FixedDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz: object = None) -> FixedDatetime:
                return cls(2026, 8, 30, 13, 0, 0)

        class FixedDatetimeModule:
            datetime = FixedDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        events: list[str] = []

        def fake_fetch(config: object, *, days: int) -> dict[str, object]:
            self.assertEqual(days, 5)
            return {
                "ok": True,
                "days": [
                    {
                        "date": "2026-08-30",
                        "courts": {"1号风雨场": [["16:00", "18:00"]]},
                    }
                ],
            }

        def fake_publish(*args: object, **kwargs: object) -> dict[str, bool]:
            events.append("webapp")
            return {"success": True}

        def fake_wechat(msg: str) -> list[dict[str, object]]:
            events.append("wechat")
            return [{"success": False, "error": "device_busy"}]

        dsh_watcher.fetch_inspect_payload = fake_fetch
        dsh_watcher.publish_venue_observation = fake_publish
        dsh_watcher.enqueue_wechat_message = fake_wechat
        dsh_watcher.datetime = FixedDatetimeModule
        try:
            dsh_watcher.run_check_tennis_courts()
            self.assertIn(expected_msg, FakeVariable.values.get(dsh_watcher.CACHE_KEY, []))
            self.assertEqual(events, ["webapp", "wechat"])
        finally:
            dsh_watcher.fetch_inspect_payload = original_fetch
            dsh_watcher.publish_venue_observation = original_publish
            dsh_watcher.enqueue_wechat_message = original_enqueue
            dsh_watcher.datetime = original_datetime

    def test_night_hours_publish_healthy_empty_observation(self) -> None:
        original_datetime = dsh_watcher.datetime
        original_publish = dsh_watcher.publish_venue_observation
        original_fetch = dsh_watcher.fetch_inspect_payload
        events: list[tuple[object, ...]] = []

        class NightDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz: object = None) -> NightDatetime:
                return cls(2026, 8, 30, 2, 0, 0)

        class NightDatetimeModule:
            datetime = NightDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        def fake_publish(*args: object, **kwargs: object) -> dict[str, bool]:
            events.append((args, kwargs))
            return {"success": True}

        def fail_fetch(*args: object, **kwargs: object) -> dict[str, object]:
            raise AssertionError("night hours must not scrape")

        dsh_watcher.datetime = NightDatetimeModule
        dsh_watcher.publish_venue_observation = fake_publish
        dsh_watcher.fetch_inspect_payload = fail_fetch
        try:
            dsh_watcher.run_check_tennis_courts()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0][0][:3], ("dsh", "大沙河国际网球中心", []))
            self.assertEqual(events[0][1], {"healthy": True})
        finally:
            dsh_watcher.datetime = original_datetime
            dsh_watcher.publish_venue_observation = original_publish
            dsh_watcher.fetch_inspect_payload = original_fetch

    def test_fetch_inspect_payload_uses_localhost_curl(self) -> None:
        captured: dict[str, object] = {}

        def fake_exec(*args: object, **kwargs: object) -> tuple[str, str, int]:
            captured["args"] = args
            return '{"ok": true, "days": []}', "", 0

        original_exec = dsh_client.exec_pi_command
        dsh_client.exec_pi_command = fake_exec
        try:
            payload = dsh_client.fetch_inspect_payload(
                dsh_client.PiDeviceConfig.from_value(FakeVariable.values["PI_DEVICE_SSH"]),
                days=5,
            )
        finally:
            dsh_client.exec_pi_command = original_exec
        self.assertEqual(payload, {"ok": True, "days": []})
        command = str(captured["args"][5])
        self.assertIn("curl -sS --fail --max-time 150", command)
        self.assertIn("http://127.0.0.1:8788/inspect?days=5", command)


if __name__ == "__main__":
    unittest.main()
