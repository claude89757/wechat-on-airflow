#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
import types
import unittest


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
    airflow_sdk_module.Variable = FakeVariable
    sys.modules.setdefault("airflow", airflow_module)
    sys.modules.setdefault("airflow.sdk", airflow_sdk_module)


install_import_stubs()
baoti_client = importlib.import_module("wechat_airflow.venues.baoti_ydmap_client")
baoti_watcher = importlib.import_module("wechat_airflow.venues.baoti_ydmap_watcher")
dsh_client = importlib.import_module("wechat_airflow.venues.dsh_ydmap_client")
baoti_watcher.Variable = FakeVariable

PI_DEVICE_SSH = {
    "host": "203.0.113.10",
    "port": 6000,
    "username": "pi-user",
    "password": "secret",
    "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
}


class BaotiYdmapWatcherTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeVariable.values = {
            "PI_DEVICE_SSH": PI_DEVICE_SSH,
            "SZ_TENNIS_CHATROOMS": "Zacks_网球场",
        }

    def test_fetch_requests_baoti_venue_with_two_day_horizon(self) -> None:
        captured: dict[str, object] = {}

        def fake_exec(*args: object, **kwargs: object) -> tuple[str, str, int]:
            captured["args"] = args
            return '{"ok": true, "days": []}', "", 0

        original_exec = baoti_client.exec_pi_command
        baoti_client.exec_pi_command = fake_exec
        try:
            payload = baoti_client.fetch_inspect_payload(
                dsh_client.PiDeviceConfig.from_value(PI_DEVICE_SSH)
            )
        finally:
            baoti_client.exec_pi_command = original_exec

        self.assertEqual(payload, {"ok": True, "days": []})
        command = str(captured["args"][5])
        self.assertIn("curl -sS --fail --max-time 240", command)
        self.assertIn("http://127.0.0.1:8788/inspect?venue=baoti&days=2", command)

    def test_parse_payload_accepts_prefixed_court_groups(self) -> None:
        parsed = dsh_client.parse_inspect_payload(
            {
                "ok": True,
                "captcha": False,
                "days": [
                    {
                        "date": "2026-10-31",
                        "courts": {
                            "室外场1号": [["11:00", "12:00"]],
                            "室内A号场": [["19:00", "20:00"]],
                            "": [["10:00", "11:00"]],
                        },
                    }
                ],
            }
        )
        self.assertEqual(
            parsed,
            {"2026-10-31": {"室外场1号": [["11:00", "12:00"]], "室内A号场": [["19:00", "20:00"]]}},
        )

    def test_canonicalize_merges_half_hour_cells(self) -> None:
        merged = baoti_watcher.canonicalize_court_availability(
            {"室外场3号": [["19:00", "19:30"], ["19:30", "20:00"], ["21:00", "21:30"]]}
        )
        self.assertEqual(merged, {"室外场3号": [["19:00", "20:00"], ["21:00", "21:30"]]})

    def test_notification_filter_requires_one_hour(self) -> None:
        filtered = baoti_watcher.filter_court_data_for_notification(
            "2026-10-31", {"室外场3号": [["19:00", "19:30"], ["20:00", "22:00"]]}
        )
        self.assertEqual(
            filtered,
            [
                {
                    "date": "2026-10-31",
                    "court_name": "宝安网球中心·室外场3号",
                    "free_slot_list": [["20:00", "22:00"]],
                }
            ],
        )

    def test_quiet_hours_publish_empty_healthy_observation(self) -> None:
        original_datetime = baoti_watcher.datetime
        original_publish = baoti_watcher.publish_venue_observation
        original_fetch = baoti_watcher.fetch_inspect_payload

        class QuietDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz: object = None) -> QuietDatetime:
                return cls(2026, 10, 30, 3, 0, 0)

        class QuietDatetimeModule:
            datetime = QuietDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        published: list[dict[str, object]] = []

        def fake_publish(*args: object, **kwargs: object) -> dict[str, bool]:
            published.append({"args": args, "kwargs": kwargs})
            return {"success": True}

        def fail_fetch(*args: object, **kwargs: object) -> dict[str, object]:
            raise AssertionError("quiet hours must not scrape the venue")

        baoti_watcher.publish_venue_observation = fake_publish
        baoti_watcher.fetch_inspect_payload = fail_fetch
        baoti_watcher.datetime = QuietDatetimeModule
        try:
            baoti_watcher.run_check_tennis_courts()
        finally:
            baoti_watcher.datetime = original_datetime
            baoti_watcher.publish_venue_observation = original_publish
            baoti_watcher.fetch_inspect_payload = original_fetch

        self.assertEqual(len(published), 1)
        self.assertEqual(published[0]["args"], ("baoti", "宝安网球中心", []))
        self.assertIs(published[0]["kwargs"].get("healthy"), True)

    def test_run_publishes_then_notifies_once_without_premature_booking_url(self) -> None:
        original_fetch = baoti_watcher.fetch_inspect_payload
        original_publish = baoti_watcher.publish_venue_observation
        original_enqueue = baoti_watcher.enqueue_wechat_message
        original_datetime = baoti_watcher.datetime

        class DayDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz: object = None) -> DayDatetime:
                return cls(2026, 10, 30, 9, 30, 0)

        class DayDatetimeModule:
            datetime = DayDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        order: list[str] = []
        messages: list[str] = []
        payload = {
            "schema_version": 2,
            "venue": "baoti",
            "ok": True,
            "captcha": False,
            "days": [
                {
                    "date": "2026-10-31",
                    "courts": {
                        "室外场1号": [["11:00", "11:30"], ["11:30", "12:00"]],
                        "室内A号场": [["19:00", "19:30"]],
                    },
                }
            ],
        }

        payload["days"].insert(0, {"date": "2026-10-30", "courts": {}})
        for day in payload["days"]:
            day["groups"] = [
                {
                    "key": key,
                    "sales_item_id": product,
                    "source_host": "bawtt.ydmap.cn",
                    "source_sales_id": "104036",
                    "freshness": "both_source_arrays_replaced_after_date_selection",
                    "load_generation": 2,
                    "data_version": {"platforms": 3, "orders": 4},
                    "product_name": label + "网球场",
                    "source_date": day["date"],
                    "selected_date": day["date"],
                    "court_names": [court],
                    "cell_count": 24,
                }
                for key, product, label, court in (
                    ("outdoor", "111317", "室外", "室外场1号"),
                    ("indoor", "103224", "室内", "室内A号场"),
                    ("windrain", "111319", "风雨", "风雨场1号"),
                )
            ]

        def fake_fetch(config: object, *, days: int) -> dict[str, object]:
            self.assertEqual(days, 2)
            return payload

        def fake_publish(*args: object, **kwargs: object) -> dict[str, bool]:
            order.append("publish")
            return {"success": True}

        def fake_enqueue(message: str) -> object:
            order.append("wechat")
            messages.append(message)
            return {"success": True}

        baoti_watcher.fetch_inspect_payload = fake_fetch
        baoti_watcher.publish_venue_observation = fake_publish
        baoti_watcher.enqueue_wechat_message = fake_enqueue
        baoti_watcher.datetime = DayDatetimeModule
        try:
            baoti_watcher.run_check_tennis_courts()
            baoti_watcher.run_check_tennis_courts()
        finally:
            baoti_watcher.datetime = original_datetime
            baoti_watcher.fetch_inspect_payload = original_fetch
            baoti_watcher.publish_venue_observation = original_publish
            baoti_watcher.enqueue_wechat_message = original_enqueue

        self.assertEqual(order.index("wechat"), 1)
        self.assertEqual(order[0], "publish")
        self.assertEqual(len(order), 3)
        self.assertEqual(len(messages), 1)
        self.assertIn("【宝安网球中心·室外场1号】星期六(10-31)空场: 11:00-12:00", messages[0])
        self.assertNotIn("室内A号场", messages[0])
        self.assertEqual(messages[0], "【宝安网球中心·室外场1号】星期六(10-31)空场: 11:00-12:00")
        self.assertEqual(
            FakeVariable.values["宝安网球中心"],
            ["【宝安网球中心·室外场1号】星期六(10-31)空场: 11:00-12:00"],
        )


if __name__ == "__main__":
    unittest.main()
