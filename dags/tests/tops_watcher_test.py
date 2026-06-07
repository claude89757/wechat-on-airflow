#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import importlib
import sys
import types
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DAGS_DIR = ROOT_DIR / "dags"
if str(DAGS_DIR) not in sys.path:
    sys.path.insert(0, str(DAGS_DIR))


class FakeDAG:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class FakePythonOperator:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class FakeVariable:
    values = {}

    @classmethod
    def get(cls, key, default_var=None, deserialize_json=False):
        return cls.values.get(key, default_var)

    @classmethod
    def set(cls, key, value, description=None, serialize_json=False):
        cls.values[key] = value


def install_import_stubs():
    airflow_module = types.ModuleType("airflow")
    airflow_module.DAG = FakeDAG

    operators_module = types.ModuleType("airflow.operators")
    python_module = types.ModuleType("airflow.operators.python")
    python_module.PythonOperator = FakePythonOperator

    models_module = types.ModuleType("airflow.models")
    models_module.Variable = FakeVariable

    tencent_ses_module = types.ModuleType("tennis_dags.utils.tencent_ses")
    tencent_ses_module.send_template_email = lambda **kwargs: {"ok": True}

    sys.modules["airflow"] = airflow_module
    sys.modules["airflow.operators"] = operators_module
    sys.modules["airflow.operators.python"] = python_module
    sys.modules["airflow.models"] = models_module
    sys.modules["tennis_dags.utils.tencent_ses"] = tencent_ses_module


install_import_stubs()
tops_watcher = importlib.import_module("tennis_dags.sz_tennis.tops_watcher")


class TopsWatcherTest(unittest.TestCase):
    def setUp(self):
        FakeVariable.values = {}

    def test_parse_tops_response_normalizes_end_times_and_merges_available_slots(self):
        response_data = {
            "successed": True,
            "status": "success",
            "result": {
                "slots": [
                    {
                        "classRoomName": "风雨棚1号场",
                        "beginDatetime": "2026-06-10 07:00:00",
                        "endDatetime": "2026-06-10 07:59:00",
                        "apptInfo": {"canApptOrNot": True},
                    },
                    {
                        "classRoomName": "风雨棚1号场",
                        "beginDatetime": "2026-06-10 08:00:00",
                        "endDatetime": "2026-06-10 08:59:00",
                        "apptInfo": {"canApptOrNot": True},
                    },
                    {
                        "classRoomName": "风雨棚1号场",
                        "beginDatetime": "2026-06-10 09:00:00",
                        "endDatetime": "2026-06-10 09:59:00",
                        "apptInfo": {"canApptOrNot": False},
                    },
                    {
                        "classRoomName": "风雨棚1号场",
                        "beginDatetime": "2026-06-10 23:00:00",
                        "endDatetime": "2026-06-10 23:59:00",
                        "apptInfo": {"canApptOrNot": True},
                    },
                ]
            },
        }

        result = tops_watcher.parse_tops_availability(response_data)

        self.assertEqual(
            result,
            {
                "风雨棚1号场": [
                    ["07:00", "09:00"],
                    ["23:00", "24:00"],
                ]
            },
        )

    def test_filter_slots_uses_sysh_weekday_and_weekend_windows(self):
        weekday_result = tops_watcher.filter_court_data_for_notification(
            "2026-06-08",
            {
                "风雨棚1号场": [
                    ["17:00", "18:00"],
                    ["18:00", "18:30"],
                    ["18:00", "19:00"],
                    ["21:30", "22:30"],
                ]
            },
        )
        weekend_result = tops_watcher.filter_court_data_for_notification(
            "2026-06-13",
            {
                "室外3号场": [
                    ["15:00", "16:00"],
                    ["16:00", "17:00"],
                ]
            },
        )

        self.assertEqual(
            weekday_result,
            [
                {
                    "date": "06-08",
                    "court_name": "TOPS科技园风雨棚1号场",
                    "free_slot_list": [["18:00", "19:00"], ["21:30", "22:30"]],
                }
            ],
        )
        self.assertEqual(
            weekend_result,
            [
                {
                    "date": "06-13",
                    "court_name": "TOPS科技园室外3号场",
                    "free_slot_list": [["16:00", "17:00"]],
                }
            ],
        )

    def test_build_new_notifications_skips_already_sent_messages(self):
        data_list = [
            {
                "date": "06-08",
                "court_name": "TOPS科技园风雨棚1号场",
                "free_slot_list": [["18:00", "19:00"], ["19:00", "20:00"]],
            }
        ]
        sent_messages = [
            "【TOPS科技园风雨棚1号场】星期一(06-08)空场: 18:00-19:00"
        ]

        messages, email_payloads = tops_watcher.build_new_notifications(
            data_list,
            sent_messages,
            current_year=2026,
        )

        self.assertEqual(
            messages,
            ["【TOPS科技园风雨棚1号场】星期一(06-08)空场: 19:00-20:00"],
        )
        self.assertEqual(
            email_payloads,
            [
                {
                    "date": "06-08",
                    "court_name": "TOPS科技园风雨棚1号场",
                    "start_time": "19:00",
                    "end_time": "20:00",
                }
            ],
        )

    def test_proxy_cache_is_independent_and_empty_proxy_list_does_not_call_api_directly(self):
        FakeVariable.values = {tops_watcher.PROXY_CACHE_KEY: ["old-proxy:8080"]}

        tops_watcher.update_proxy_cache("new-proxy:8080", True)
        tops_watcher.update_proxy_cache("old-proxy:8080", False)

        self.assertEqual(
            FakeVariable.values[tops_watcher.PROXY_CACHE_KEY],
            ["new-proxy:8080"],
        )

        original_post = tops_watcher.requests.post

        def fail_if_called(*args, **kwargs):
            raise AssertionError("TOPS API should not be called directly without a proxy")

        tops_watcher.requests.post = fail_if_called
        FakeVariable.values = {}
        try:
            with self.assertRaisesRegex(Exception, "all proxies failed"):
                tops_watcher.get_tennis_court_availability("2026-06-10", [])
        finally:
            tops_watcher.requests.post = original_post


if __name__ == "__main__":
    unittest.main()
