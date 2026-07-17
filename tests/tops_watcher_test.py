#!/usr/bin/env python3
import importlib
import sys
import types
import unittest


class FakeDAG:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakePythonOperator:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    def __rshift__(self, other):
        return other


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
    airflow_sdk_module = types.ModuleType("airflow.sdk")
    airflow_sdk_module.DAG = FakeDAG
    airflow_sdk_module.Variable = FakeVariable

    operators_module = types.ModuleType("airflow.operators")
    providers_module = types.ModuleType("airflow.providers")
    standard_module = types.ModuleType("airflow.providers.standard")
    standard_operators_module = types.ModuleType("airflow.providers.standard.operators")
    python_module = types.ModuleType("airflow.providers.standard.operators.python")
    python_module.PythonOperator = FakePythonOperator

    sys.modules["airflow"] = airflow_module
    sys.modules["airflow.sdk"] = airflow_sdk_module
    sys.modules["airflow.operators"] = operators_module
    sys.modules["airflow.providers"] = providers_module
    sys.modules["airflow.providers.standard"] = standard_module
    sys.modules["airflow.providers.standard.operators"] = standard_operators_module
    sys.modules["airflow.providers.standard.operators.python"] = python_module


install_import_stubs()
jdwx_watcher = importlib.import_module("wechat_airflow.venues.jdwx_watcher")
sysh_watcher = importlib.import_module("wechat_airflow.venues.sysh_watcher")
szw_watcher = importlib.import_module("wechat_airflow.venues.szw_watcher")
tops_watcher = importlib.import_module("wechat_airflow.venues.tops_watcher")
tyzx_watcher = importlib.import_module("wechat_airflow.venues.tyzx_watcher")


class VenueDomainTest(unittest.TestCase):
    def test_jdwx_merges_touching_and_overlapping_slots(self):
        self.assertEqual(
            jdwx_watcher.merge_time_ranges(
                [["08:00", "09:00"], ["08:30", "10:00"], ["10:00", "11:00"]]
            ),
            [["08:00", "11:00"]],
        )

    def test_sysh_normalizes_and_merges_slots(self):
        self.assertEqual(sysh_watcher.normalize_time("6:05"), "06:05")
        self.assertEqual(
            sysh_watcher.merge_time_ranges([["23:00", "24:00"], ["22:00", "23:00"]]),
            [["22:00", "24:00"]],
        )

    def test_szw_finds_gaps_within_notification_window(self):
        self.assertEqual(
            szw_watcher.find_available_slots(
                [["08:00", "09:00"], ["10:00", "11:00"]],
                {"start_time": "07:00", "end_time": "12:00"},
            ),
            [["07:00", "08:00"], ["09:00", "10:00"], ["11:00", "12:00"]],
        )
        self.assertEqual(
            szw_watcher.extract_time_hhmm("2026-07-17 08:30:00"),
            "08:30",
        )

    def test_tyzx_only_merges_available_unlocked_slots(self):
        result = tyzx_watcher.parse_tyzx_court_data(
            {
                "body": [
                    {
                        "placeName": "1号场",
                        "startTime": "07:00:00",
                        "endTime": "08:00:00",
                        "appointFlag": 1,
                        "priceInfoList": [{"price": 100, "remainnum": 1}],
                    },
                    {
                        "placeName": "1号场",
                        "startTime": "08:00:00",
                        "endTime": "09:00:00",
                        "appointFlag": 1,
                        "priceInfoList": [{"price": 100, "remainnum": 1}],
                    },
                    {
                        "placeName": "1号场",
                        "startTime": "09:00:00",
                        "endTime": "10:00:00",
                        "appointFlag": 1,
                        "lockRemark": "maintenance",
                        "priceInfoList": [{"price": 100, "remainnum": 1}],
                    },
                ]
            }
        )

        self.assertEqual(result, {"1号场": [["07:00", "09:00"]]})


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
        sent_messages = ["【TOPS科技园风雨棚1号场】星期一(06-08)空场: 18:00-19:00"]

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

    def test_check_tennis_courts_keeps_email_and_cache_when_wechat_falls_back(self):
        FakeVariable.values = {}
        expected_msg = "【TOPS科技园室外6号场】星期六(07-11)空场: 07:00-17:00"

        original_load_proxy = tops_watcher.load_proxy_list
        original_get_availability = tops_watcher.get_tennis_court_availability
        original_send_email = tops_watcher.send_email_notifications
        original_enqueue = tops_watcher.enqueue_wechat_message
        original_datetime = tops_watcher.datetime

        class FixedDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 7, 9, 13, 0, 0)

        class FixedDatetimeModule:
            datetime = FixedDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        def fake_get_availability(date, proxy_list):
            if date == "2026-07-11":
                return {"室外6号场": [["07:00", "17:00"]]}
            return {}

        email_calls = []
        wechat_calls = []

        def fake_send_email(payloads):
            email_calls.append(payloads)

        def fallback_wechat(msg):
            wechat_calls.append(msg)
            return [{"success": False, "error": "device_busy"}]

        tops_watcher.load_proxy_list = lambda: []
        tops_watcher.get_tennis_court_availability = fake_get_availability
        tops_watcher.send_email_notifications = fake_send_email
        tops_watcher.enqueue_wechat_message = fallback_wechat
        tops_watcher.datetime = FixedDatetimeModule

        try:
            tops_watcher.run_check_tennis_courts()

            self.assertIn(expected_msg, FakeVariable.values.get(tops_watcher.CACHE_KEY, []))
            self.assertEqual(len(email_calls), 1)
            self.assertEqual(wechat_calls, [expected_msg])
        finally:
            tops_watcher.load_proxy_list = original_load_proxy
            tops_watcher.get_tennis_court_availability = original_get_availability
            tops_watcher.send_email_notifications = original_send_email
            tops_watcher.enqueue_wechat_message = original_enqueue
            tops_watcher.datetime = original_datetime


if __name__ == "__main__":
    unittest.main()
