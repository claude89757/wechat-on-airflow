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
ppba_watcher = importlib.import_module("wechat_airflow.venues.ppba_watcher")
ppba_watcher.Variable = FakeVariable


class PpbaWatcherTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeVariable.values = {}

    def test_parse_availability_keeps_tennis_and_drops_pickleball(self) -> None:
        result = ppba_watcher.parse_availability(
            {
                "successed": True,
                "status": "success",
                "result": {
                    "slots": [
                        {
                            "classRoomName": "网球1号澳网风 （VIP风雨馆）",
                            "beginDatetime": "2026-08-31 18:00:00",
                            "endDatetime": "2026-08-31 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "网球1号澳网风 （VIP风雨馆）",
                            "beginDatetime": "2026-08-31 19:00:00",
                            "endDatetime": "2026-08-31 19:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "网球3号法网风   （VIP风雨馆）",
                            "beginDatetime": "2026-08-31 23:00:00",
                            "endDatetime": "2026-08-31 23:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "匹克球1号 （VIP风雨馆）",
                            "beginDatetime": "2026-08-31 18:00:00",
                            "endDatetime": "2026-08-31 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "网球2号法网风（VIP风雨馆）",
                            "beginDatetime": "2026-08-31 18:00:00",
                            "endDatetime": "2026-08-31 18:59:00",
                            "apptInfo": {"canApptOrNot": False},
                        },
                    ]
                },
            }
        )

        self.assertEqual(
            result,
            {
                "网球1号澳网风 （VIP风雨馆）": [["18:00", "20:00"]],
                "网球3号法网风 （VIP风雨馆）": [["23:00", "24:00"]],
            },
        )

    def test_filter_slots_uses_weekday_and_weekend_windows(self) -> None:
        weekday_result = ppba_watcher.filter_court_data_for_notification(
            "2026-08-24",
            {
                "网球1号澳网风 （VIP风雨馆）": [
                    ["00:00", "01:00"],
                    ["06:00", "07:00"],
                    ["17:00", "18:00"],
                    ["18:00", "19:00"],
                    ["21:30", "22:30"],
                ]
            },
        )
        weekend_result = ppba_watcher.filter_court_data_for_notification(
            "2026-08-23",
            {"网球2号法网风（VIP风雨馆）": [["15:00", "16:00"], ["16:00", "17:00"]]},
        )

        self.assertEqual(
            weekday_result,
            [
                {
                    "date": "08-24",
                    "court_name": "PICKLE POP宝安网球1号澳网风 （VIP风雨馆）",
                    "free_slot_list": [["18:00", "19:00"], ["21:30", "22:30"]],
                }
            ],
        )
        self.assertEqual(
            weekend_result,
            [
                {
                    "date": "08-23",
                    "court_name": "PICKLE POP宝安网球2号法网风（VIP风雨馆）",
                    "free_slot_list": [["16:00", "17:00"]],
                }
            ],
        )

    def test_build_new_notifications_skips_already_sent_messages(self) -> None:
        messages = ppba_watcher.build_new_notifications(
            [
                {
                    "date": "08-24",
                    "court_name": "PICKLE POP宝安网球1号澳网风 （VIP风雨馆）",
                    "free_slot_list": [["18:00", "19:00"], ["19:00", "20:00"]],
                }
            ],
            ["【PICKLE POP宝安网球1号澳网风 （VIP风雨馆）】星期一(08-24)空场: 18:00-19:00"],
            current_year=2026,
        )

        self.assertEqual(
            messages,
            ["【PICKLE POP宝安网球1号澳网风 （VIP风雨馆）】星期一(08-24)空场: 19:00-20:00"],
        )

    def test_empty_proxy_list_does_not_call_api_directly(self) -> None:
        original_post = ppba_watcher.requests.post

        def fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("PPBA API should not be called directly without a proxy")

        ppba_watcher.requests.post = fail_if_called
        try:
            with self.assertRaisesRegex(Exception, "all proxies failed"):
                ppba_watcher.get_tennis_court_availability("2026-08-24", [])
        finally:
            ppba_watcher.requests.post = original_post

    def test_check_tennis_courts_publishes_webapp_before_wechat(self) -> None:
        expected_msg = "【PICKLE POP宝安网球3号法网风 （VIP风雨馆）】星期日(08-23)空场: 16:00-18:00"
        original_load_proxy = ppba_watcher.load_proxy_list
        original_get_availability = ppba_watcher.get_tennis_court_availability
        original_publish = ppba_watcher.publish_venue_observation
        original_enqueue = ppba_watcher.enqueue_wechat_message
        original_datetime = ppba_watcher.datetime

        class FixedDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz: object = None) -> FixedDatetime:
                return cls(2026, 8, 23, 13, 0, 0)

        class FixedDatetimeModule:
            datetime = FixedDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        def fake_get_availability(date: str, proxy_list: list[str]) -> dict[str, list[list[str]]]:
            if date == "2026-08-23":
                return {"网球3号法网风 （VIP风雨馆）": [["16:00", "18:00"]]}
            return {}

        events: list[str] = []
        observations: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def fake_publish(*args: object, **kwargs: object) -> dict[str, bool]:
            events.append("webapp")
            observations.append((args, kwargs))
            return {"success": True}

        def fallback_wechat(msg: str) -> list[dict[str, object]]:
            events.append("wechat")
            return [{"success": False, "error": "device_busy"}]

        ppba_watcher.load_proxy_list = lambda: []
        ppba_watcher.get_tennis_court_availability = fake_get_availability
        ppba_watcher.publish_venue_observation = fake_publish
        ppba_watcher.enqueue_wechat_message = fallback_wechat
        ppba_watcher.datetime = FixedDatetimeModule
        try:
            ppba_watcher.run_check_tennis_courts()
            self.assertIn(expected_msg, FakeVariable.values.get(ppba_watcher.CACHE_KEY, []))
            self.assertEqual(events, ["webapp", "wechat"])
            self.assertEqual(observations[0][0][0:2], ("ppba", "PICKLE POP宝安"))
        finally:
            ppba_watcher.load_proxy_list = original_load_proxy
            ppba_watcher.get_tennis_court_availability = original_get_availability
            ppba_watcher.publish_venue_observation = original_publish
            ppba_watcher.enqueue_wechat_message = original_enqueue
            ppba_watcher.datetime = original_datetime


if __name__ == "__main__":
    unittest.main()
