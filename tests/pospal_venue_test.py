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
pospal_venue = importlib.import_module("wechat_airflow.venues.pospal_venue")
pospal_venue.Variable = FakeVariable
fsb_shenyun_watcher = importlib.import_module("wechat_airflow.venues.fsb_shenyun_watcher")
fft_qianhai_watcher = importlib.import_module("wechat_airflow.venues.fft_qianhai_watcher")


class PosPalVenueTest(unittest.TestCase):
    def setUp(self) -> None:
        FakeVariable.values = {}

    def test_standard_tennis_courts_exclude_small_pickleball_and_practice(self) -> None:
        self.assertTrue(pospal_venue.is_standard_tennis_court("1号场"))
        self.assertTrue(pospal_venue.is_standard_tennis_court("9号风雨场"))
        self.assertTrue(pospal_venue.is_standard_tennis_court("3号场【常用】"))
        self.assertTrue(pospal_venue.is_standard_tennis_court("2号红土风雨场"))
        self.assertTrue(pospal_venue.is_standard_tennis_court("标准场"))
        self.assertFalse(pospal_venue.is_standard_tennis_court("网球小场"))
        self.assertFalse(pospal_venue.is_standard_tennis_court("1号匹克球场"))
        self.assertFalse(pospal_venue.is_standard_tennis_court("练习场【常用】"))
        self.assertFalse(pospal_venue.is_standard_tennis_court("E栋3号场（非标场）"))
        self.assertFalse(pospal_venue.is_standard_tennis_court("4号非标准场"))
        self.assertFalse(pospal_venue.is_standard_tennis_court("室内发球机"))
        self.assertFalse(pospal_venue.is_standard_tennis_court("1号场室内发球机"))

    def test_parse_availability_keeps_only_standard_bookable_courts(self) -> None:
        result = pospal_venue.parse_availability(
            {
                "successed": True,
                "status": "success",
                "result": {
                    "slots": [
                        {
                            "classRoomName": "1号场",
                            "beginDatetime": "2026-08-29 18:00:00",
                            "endDatetime": "2026-08-29 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "9号风雨场",
                            "beginDatetime": "2026-08-29 18:00:00",
                            "endDatetime": "2026-08-29 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "网球小场",
                            "beginDatetime": "2026-08-29 18:00:00",
                            "endDatetime": "2026-08-29 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "1号匹克球场",
                            "beginDatetime": "2026-08-29 18:00:00",
                            "endDatetime": "2026-08-29 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "练习场",
                            "beginDatetime": "2026-08-29 18:00:00",
                            "endDatetime": "2026-08-29 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "4号非标准场",
                            "beginDatetime": "2026-08-29 18:00:00",
                            "endDatetime": "2026-08-29 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                        {
                            "classRoomName": "室内发球机",
                            "beginDatetime": "2026-08-29 18:00:00",
                            "endDatetime": "2026-08-29 18:59:00",
                            "apptInfo": {"canApptOrNot": True},
                        },
                    ]
                },
            }
        )

        self.assertEqual(
            result,
            {
                "1号场": [["18:00", "19:00"]],
                "9号风雨场": [["18:00", "19:00"]],
            },
        )

    def test_fft_qianhai_configuration_matches_verified_public_ids(self) -> None:
        venue = pospal_venue.FFT_QIANHAI

        self.assertEqual(venue.venue_id, "fft_qianhai")
        self.assertEqual(venue.venue_name, "FFTENNIS前海国际网球中心")
        self.assertEqual(venue.store_id, "5934657")
        self.assertEqual(venue.project_uid, "1756717886546691955")
        self.assertTrue(venue.try_direct_first)
        self.assertTrue(venue.verify_tls)
        self.assertTrue(venue.include_user_id)
        self.assertEqual(venue.notification_baseline_key, "FFT_QIANHAI_NOTIFICATION_BASELINE")
        self.assertIn("非标", venue.excluded_court_tokens)
        self.assertIn("发球机", venue.excluded_court_tokens)
        self.assertEqual(venue.allowed_court_numbers, frozenset(range(1, 7)))

    def test_fft_qianhai_direct_query_uses_public_contract_and_filters_rooms(self) -> None:
        original_post = pospal_venue.requests.post
        original_sleep = pospal_venue.time.sleep
        captured: dict[str, object] = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json() -> dict[str, object]:
                return {
                    "successed": True,
                    "status": "success",
                    "result": {
                        "validClassRooms": [{"name": "1号（双打场）"}],
                        "slots": [
                            {
                                "classRoomName": "1号（双打场）",
                                "beginDatetime": "2026-08-30 18:00:00",
                                "endDatetime": "2026-08-30 18:59:00",
                                "apptInfo": {"canApptOrNot": True},
                            },
                            {
                                "classRoomName": "7号（非标单打场）",
                                "beginDatetime": "2026-08-30 18:00:00",
                                "endDatetime": "2026-08-30 18:59:00",
                                "apptInfo": {"canApptOrNot": True},
                            },
                            {
                                "classRoomName": "9号（发球机场）",
                                "beginDatetime": "2026-08-30 18:00:00",
                                "endDatetime": "2026-08-30 18:59:00",
                                "apptInfo": {"canApptOrNot": True},
                            },
                        ],
                    },
                }

        def fake_post(url: str, **kwargs: object) -> FakeResponse:
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

        pospal_venue.requests.post = fake_post
        pospal_venue.time.sleep = lambda *_args, **_kwargs: None
        try:
            result = pospal_venue.get_tennis_court_availability(
                pospal_venue.FFT_QIANHAI, "2026-08-30", ["https://proxy.invalid"]
            )
        finally:
            pospal_venue.requests.post = original_post
            pospal_venue.time.sleep = original_sleep

        self.assertEqual(result, {"1号（双打场）": [["18:00", "19:00"]]})
        self.assertEqual(captured["url"], pospal_venue.POSPAL_API_URL)
        self.assertNotIn("proxies", captured)
        self.assertIs(captured["verify"], True)
        self.assertEqual(
            captured["json"],
            {
                "dateTime": "2026-08-30",
                "projectUid": "1756717886546691955",
                "userId": 5934657,
            },
        )
        headers = captured["headers"]
        self.assertIsInstance(headers, dict)
        assert isinstance(headers, dict)
        self.assertEqual(headers["STOREID"], "5934657")
        self.assertEqual(headers["PSPLVISITORAUTO"], "API")
        self.assertEqual(headers["APPTYPE"], "1")
        self.assertEqual(headers["VERSIONINFO"], "NC|2026.07.25")

    def test_empty_proxy_list_does_not_call_api_directly(self) -> None:
        original_post = pospal_venue.requests.post

        def fail_if_called(*args: object, **kwargs: object) -> None:
            raise AssertionError("PosPal API should not be called directly without a proxy")

        pospal_venue.requests.post = fail_if_called
        try:
            with self.assertRaisesRegex(Exception, "all proxies failed"):
                pospal_venue.get_tennis_court_availability(
                    pospal_venue.FSB_SHENYUN, "2026-08-29", []
                )
        finally:
            pospal_venue.requests.post = original_post

    def test_notification_filter_drops_small_pickleball_and_practice_courts(self) -> None:
        filtered = pospal_venue.filter_court_data_for_notification(
            pospal_venue.FSB_SHEKOU,
            "2026-08-29",
            {
                "1号场": [["16:00", "18:00"]],
                "网球小场": [["16:00", "18:00"]],
                "1号匹克球场": [["16:00", "18:00"]],
                "练习场": [["16:00", "18:00"]],
                "4号非标准场": [["16:00", "18:00"]],
                "室内发球机": [["16:00", "18:00"]],
            },
        )

        self.assertEqual(
            [item["court_name"] for item in filtered],
            ["泛思博特蛇口1号场"],
        )

    def test_chain_venues_use_shared_project_and_distinct_stores(self) -> None:
        self.assertEqual(
            {venue.venue_id: venue.store_id for venue in pospal_venue.CHAIN_VENUES.values()},
            {
                "fsb_shenyun": "6019572",
                "fsb_shekou": "6019561",
                "fsb_xinan": "6019579",
                "fsb_zhengzhong": "6019533",
                "fsb_atuoshan": "6019581",
                "fsb_zonglvquan": "6003756",
                "fsb_guanhu": "6019554",
                "fsb_bantian": "6019542",
                "fsb_shahe": "6003754",
                "fsb_baoshui": "6019577",
                "fsb_nanyou": "6019557",
                "fsb_xinqiao": "6019571",
                "fsb_yifangcheng": "6019568",
                "fsb_qilin": "6019569",
                "fsb_maozhouhe": "6019555",
            },
        )
        self.assertTrue(
            all(
                venue.project_uid == pospal_venue.FSB_CHAIN_PROJECT_UID
                for venue in pospal_venue.CHAIN_VENUES.values()
            )
        )

    def test_fft_first_successful_observation_warm_starts_without_wechat(self) -> None:
        expected_msg = "【FFTENNIS前海国际网球中心1号（双打场）】星期日(08-30)空场: 16:00-18:00"
        original_load_proxy = pospal_venue.load_proxy_list
        original_get_availability = pospal_venue.get_tennis_court_availability
        original_publish = pospal_venue.publish_venue_observation
        original_enqueue = pospal_venue.enqueue_wechat_message
        original_datetime = pospal_venue.datetime
        original_sleep = pospal_venue.time.sleep

        class FixedDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz: object = None) -> FixedDatetime:
                return cls(2026, 8, 30, 13, 0, 0)

        class FixedDatetimeModule:
            datetime = FixedDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        def fake_get_availability(
            venue: object, date: str, proxy_list: list[str]
        ) -> dict[str, list[list[str]]]:
            self.assertEqual(venue, pospal_venue.FFT_QIANHAI)
            if date == "2026-08-30":
                return {"1号（双打场）": [["16:00", "18:00"]]}
            return {}

        events: list[str] = []

        def fake_publish(*_args: object, **_kwargs: object) -> dict[str, bool]:
            events.append("webapp")
            return {"success": True}

        def unexpected_wechat(_venue: object, _msg: str) -> object:
            events.append("wechat")
            raise AssertionError("warm-start must not send WeChat")

        pospal_venue.load_proxy_list = lambda: []
        pospal_venue.get_tennis_court_availability = fake_get_availability
        pospal_venue.publish_venue_observation = fake_publish
        pospal_venue.enqueue_wechat_message = unexpected_wechat
        pospal_venue.datetime = FixedDatetimeModule
        pospal_venue.time.sleep = lambda *_args, **_kwargs: None
        try:
            fft_qianhai_watcher.run_check_tennis_courts()
        finally:
            pospal_venue.load_proxy_list = original_load_proxy
            pospal_venue.get_tennis_court_availability = original_get_availability
            pospal_venue.publish_venue_observation = original_publish
            pospal_venue.enqueue_wechat_message = original_enqueue
            pospal_venue.datetime = original_datetime
            pospal_venue.time.sleep = original_sleep

        self.assertEqual(events, ["webapp"])
        self.assertIn(expected_msg, FakeVariable.values[pospal_venue.FFT_QIANHAI.cache_key])
        marker = FakeVariable.values[pospal_venue.FFT_NOTIFICATION_BASELINE_KEY]
        self.assertIsInstance(marker, dict)
        assert isinstance(marker, dict)
        self.assertTrue(marker["initialized"])

    def test_check_publishes_webapp_before_wechat_and_filters_courts(self) -> None:
        expected_msg = "【泛思博特深云1号场】星期六(08-29)空场: 16:00-18:00"
        original_load_proxy = pospal_venue.load_proxy_list
        original_get_availability = pospal_venue.get_tennis_court_availability
        original_publish = pospal_venue.publish_venue_observation
        original_enqueue = pospal_venue.enqueue_wechat_message
        original_datetime = pospal_venue.datetime
        original_sleep = pospal_venue.time.sleep

        class FixedDatetime(original_datetime.datetime):
            @classmethod
            def now(cls, tz: object = None) -> FixedDatetime:
                return cls(2026, 8, 29, 13, 0, 0)

        class FixedDatetimeModule:
            datetime = FixedDatetime
            time = original_datetime.time
            timedelta = original_datetime.timedelta

        def fake_get_availability(
            venue: object, date: str, proxy_list: list[str]
        ) -> dict[str, list[list[str]]]:
            self.assertEqual(venue, pospal_venue.FSB_SHENYUN)
            if date == "2026-08-29":
                return {"1号场": [["16:00", "18:00"]]}
            return {}

        events: list[str] = []
        observations: list[tuple[tuple[object, ...], dict[str, object]]] = []

        def fake_publish(*args: object, **kwargs: object) -> dict[str, bool]:
            events.append("webapp")
            observations.append((args, kwargs))
            return {"success": True}

        def fallback_wechat(venue: object, msg: str) -> list[dict[str, object]]:
            events.append("wechat")
            self.assertEqual(venue, pospal_venue.FSB_SHENYUN)
            self.assertNotIn("小场", msg)
            return [{"success": False, "error": "device_busy"}]

        pospal_venue.load_proxy_list = lambda: []
        pospal_venue.get_tennis_court_availability = fake_get_availability
        pospal_venue.publish_venue_observation = fake_publish
        pospal_venue.enqueue_wechat_message = fallback_wechat
        pospal_venue.datetime = FixedDatetimeModule
        pospal_venue.time.sleep = lambda *_args, **_kwargs: None
        try:
            fsb_shenyun_watcher.run_check_tennis_courts()
            self.assertIn(
                expected_msg, FakeVariable.values.get(pospal_venue.FSB_SHENYUN.cache_key, [])
            )
            self.assertEqual(events, ["webapp", "wechat"])
            self.assertEqual(observations[0][0][0:2], ("fsb_shenyun", "泛思博特深云"))
            published_slots = observations[0][0][2]
            self.assertTrue(isinstance(published_slots, list))
            self.assertTrue(all("小场" not in str(slot) for slot in published_slots))
        finally:
            pospal_venue.load_proxy_list = original_load_proxy
            pospal_venue.get_tennis_court_availability = original_get_availability
            pospal_venue.publish_venue_observation = original_publish
            pospal_venue.enqueue_wechat_message = original_enqueue
            pospal_venue.datetime = original_datetime
            pospal_venue.time.sleep = original_sleep


if __name__ == "__main__":
    unittest.main()
