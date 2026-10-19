#!/usr/bin/env python3
import base64
import datetime
import importlib
import io
import json
import sys
import types
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


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
    def get(cls, key, default=None, deserialize_json=False):
        return cls.values.get(key, default)

    @classmethod
    def set(cls, key, value, description=None, serialize_json=False):
        cls.values[key] = value


class FakeAirflowFailException(Exception):
    pass


def install_import_stubs():
    airflow_module = types.ModuleType("airflow")
    airflow_sdk_module = types.ModuleType("airflow.sdk")
    airflow_sdk_exceptions_module = types.ModuleType("airflow.sdk.exceptions")
    airflow_sdk_module.DAG = FakeDAG
    airflow_sdk_module.Variable = FakeVariable
    airflow_sdk_exceptions_module.AirflowFailException = FakeAirflowFailException

    operators_module = types.ModuleType("airflow.operators")
    providers_module = types.ModuleType("airflow.providers")
    standard_module = types.ModuleType("airflow.providers.standard")
    standard_operators_module = types.ModuleType("airflow.providers.standard.operators")
    python_module = types.ModuleType("airflow.providers.standard.operators.python")
    python_module.PythonOperator = FakePythonOperator

    sys.modules["airflow"] = airflow_module
    sys.modules["airflow.sdk"] = airflow_sdk_module
    sys.modules["airflow.sdk.exceptions"] = airflow_sdk_exceptions_module
    sys.modules["airflow.operators"] = operators_module
    sys.modules["airflow.providers"] = providers_module
    sys.modules["airflow.providers.standard"] = standard_module
    sys.modules["airflow.providers.standard.operators"] = standard_operators_module
    sys.modules["airflow.providers.standard.operators.python"] = python_module


install_import_stubs()
https_proxy_watcher = importlib.import_module("wechat_airflow.proxy_tools.https_proxy_watcher")
jdwx_watcher = importlib.import_module("wechat_airflow.venues.jdwx_watcher")
sysh_watcher = importlib.import_module("wechat_airflow.venues.sysh_watcher")
szw_watcher = importlib.import_module("wechat_airflow.venues.szw_watcher")
tops_watcher = importlib.import_module("wechat_airflow.venues.tops_watcher")
tyzx_watcher = importlib.import_module("wechat_airflow.venues.tyzx_watcher")


def make_szw_authorization(
    exp: int | float,
    account: str = "test-account",
    *,
    claims: dict | None = None,
) -> str:
    def encode(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    payload = {"exp": exp, "sub": account, "openid": account, **(claims or {})}
    signature = base64.urlsafe_b64encode(b"\x00" * 32).rstrip(b"=").decode()
    return f"Wechat {encode({'alg': 'HS256', 'typ': 'JWT'})}.{encode(payload)}.{signature}"


class VenueDomainTest(unittest.TestCase):
    def setUp(self):
        FakeVariable.values = {"SZW_API_AUTHORIZATION": make_szw_authorization(4_102_444_800)}

    def test_proxy_sources_are_isolated(self):
        original_get = https_proxy_watcher.requests.get

        class FakeResponse:
            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                return None

        responses = iter(
            [
                https_proxy_watcher.requests.ConnectionError("source unavailable"),
                FakeResponse("1.2.3.4:80\ninvalid"),
                FakeResponse("5.6.7.8:443"),
            ]
        )

        def fake_get(*args, **kwargs):
            response = next(responses)
            if isinstance(response, Exception):
                raise response
            return response

        https_proxy_watcher.requests.get = fake_get
        try:
            proxies, source_map = https_proxy_watcher.generate_proxies()
        finally:
            https_proxy_watcher.requests.get = original_get

        self.assertCountEqual(proxies, ["1.2.3.4:80", "5.6.7.8:443"])
        self.assertEqual(set(source_map), set(proxies))

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

    def test_szw_rejects_expired_airflow_authorization(self):
        with self.assertRaisesRegex(ValueError, "已过期"):
            szw_watcher.validate_szw_authorization(make_szw_authorization(1), now=2)

    def test_szw_normalizes_legacy_raw_jwt_authorization(self):
        authorization = make_szw_authorization(4_102_444_800)

        self.assertEqual(
            szw_watcher.validate_szw_authorization(
                authorization.removeprefix("Wechat "),
                now=1,
            ),
            authorization,
        )

    def test_crland_request_matches_current_mini_program_contract(self):
        authorization = make_szw_authorization(4_102_444_800)
        FakeVariable.values = {"SZW_API_AUTHORIZATION": authorization}
        captured = {}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "code": 200,
                    "text": "success",
                    "result": {
                        "fieldList": [{"fieldUuid": "court-1", "fieldName": "1号场"}],
                        "matrix": [{"fieldUuid": "court-1", "matrix": []}],
                    },
                }

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            post = staticmethod(fake_post)

        with (
            patch.object(
                szw_watcher,
                "create_crland_http_session",
                return_value=FakeSession(),
            ),
            patch.object(szw_watcher.time, "sleep"),
        ):
            result = szw_watcher.get_free_tennis_court_infos_for_szw(
                "2026-08-10",
                ["不使用代理"],
                {"start_time": "09:00", "end_time": "21:00"},
                project_uuid=szw_watcher.GBA_PROJECT_UUID,
                field_area_uuid=szw_watcher.GBA_FIELD_AREA_UUID,
                court_name_prefix="大湾区",
            )

        self.assertEqual(result, {"大湾区1号场": [["09:00", "21:00"]]})
        self.assertEqual(captured["url"], szw_watcher.SZW_MATRIX_API_URL)
        self.assertEqual(
            captured["json"],
            {
                "fieldAreaUuid": "cec42d973dee11f1b51c2273436a3e4e",
                "reserveDate": "2026-08-10",
                "enterpriseUuid": "",
                "discountSpecUuid": "",
                "projectUuid": "0ddda9c33d4e11f1b51c2273436a3e4e",
            },
        )
        headers = captured["headers"]
        self.assertEqual(headers["appId"], "wx020209beec4251e0")
        self.assertEqual(headers["Authorization"], authorization)
        self.assertEqual(headers["projectUuid"], "0ddda9c33d4e11f1b51c2273436a3e4e")
        self.assertEqual(
            headers["Referer"],
            "https://servicewechat.com/wx020209beec4251e0/69/page-frame.html",
        )
        self.assertIn("Chrome/144.0.0.0", headers["User-Agent"])
        self.assertIn("XWEB/25561", headers["User-Agent"])

    def test_szw_session_enables_legacy_tls_only_for_its_host(self):
        session = szw_watcher.create_crland_http_session()
        try:
            adapter = session.adapters[f"https://{szw_watcher.SZW_HOST}/"]
            self.assertIsInstance(adapter, szw_watcher.CrlandLegacyTlsAdapter)
            self.assertTrue(adapter.ssl_context.options & szw_watcher.SSL_OP_LEGACY_SERVER_CONNECT)
            self.assertIsNot(
                session.adapters["https://"],
                adapter,
            )
        finally:
            session.close()

    def test_crland_retries_transient_forbidden_response(self):
        authorization = make_szw_authorization(4_102_444_800)
        FakeVariable.values = {"SZW_API_AUTHORIZATION": authorization}

        class FakeResponse:
            def __init__(self, status_code):
                self.status_code = status_code

            @staticmethod
            def json():
                return {
                    "code": 200,
                    "text": "success",
                    "result": {
                        "fieldList": [{"fieldUuid": "court-1", "fieldName": "1号场"}],
                        "matrix": [{"fieldUuid": "court-1", "matrix": []}],
                    },
                }

        class FakeSession:
            responses = iter([FakeResponse(403), FakeResponse(403), FakeResponse(200)])
            post_count = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, *args, **kwargs):
                self.post_count += 1
                return next(self.responses)

        session = FakeSession()
        with (
            patch.object(
                szw_watcher,
                "create_crland_http_session",
                return_value=session,
            ),
            patch.object(szw_watcher.time, "sleep") as sleep,
        ):
            result = szw_watcher.get_free_tennis_court_infos_for_szw(
                "2026-08-12",
                ["不使用代理"],
                {"start_time": "09:00", "end_time": "21:00"},
            )

        self.assertEqual(result, {"1号场": [["09:00", "21:00"]]})
        self.assertEqual(session.post_count, 3)
        self.assertEqual(
            sleep.call_args_list,
            [
                unittest.mock.call(szw_watcher.CRLAND_RETRY_DELAY_SECONDS),
                unittest.mock.call(szw_watcher.CRLAND_RETRY_DELAY_SECONDS),
                unittest.mock.call(1),
            ],
        )

    def test_crland_venues_merge_covered_courts_and_keep_gba_independent(self):
        shenzhen_bay = szw_watcher.CRLAND_VENUES["szw"]
        self.assertEqual(shenzhen_bay.venue_id, "szw")
        self.assertEqual(len(shenzhen_bay.booking_areas), 2)
        self.assertEqual(
            shenzhen_bay.booking_areas[1].field_area_uuid,
            "71abff5590af11f195a452a64e4c2bdc",
        )
        self.assertEqual(shenzhen_bay.booking_areas[1].court_name_prefix, "风雨场")
        self.assertEqual(
            (
                shenzhen_bay.booking_areas[1].start_time,
                shenzhen_bay.booking_areas[1].end_time,
            ),
            ("07:30", "22:30"),
        )

        greater_bay_area = szw_watcher.CRLAND_VENUES["gba"]
        self.assertEqual(greater_bay_area.venue_id, "gba")
        self.assertEqual(greater_bay_area.venue_name, "大湾区网球场")
        self.assertEqual(
            greater_bay_area.booking_areas[0].project_uuid,
            "0ddda9c33d4e11f1b51c2273436a3e4e",
        )
        self.assertEqual(
            greater_bay_area.booking_areas[0].field_area_uuid,
            "cec42d973dee11f1b51c2273436a3e4e",
        )
        self.assertEqual(
            (
                greater_bay_area.booking_areas[0].start_time,
                greater_bay_area.booking_areas[0].end_time,
            ),
            ("09:00", "21:00"),
        )
        self.assertEqual(greater_bay_area.weekday_wechat_hours, (18, 21))
        self.assertEqual(greater_bay_area.weekend_wechat_hours, (12, 21))
        self.assertEqual(shenzhen_bay.weekend_wechat_hours, (16, 22))

    def test_szw_publishes_outdoor_and_covered_courts_as_one_observation(self):
        class NoonDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 12, 12, 0, tzinfo=tz)

        with (
            patch.object(szw_watcher.datetime, "datetime", NoonDateTime),
            patch.object(
                szw_watcher,
                "get_free_tennis_court_infos_for_szw",
                side_effect=[
                    {"1号场": [["09:00", "10:00"]]},
                    {"风雨场网球1号": [["10:00", "11:00"]]},
                ],
            ) as get_courts,
            patch.object(szw_watcher, "publish_venue_observation") as publish,
        ):
            szw_watcher.check_and_notify_for_day(0)

        self.assertEqual(get_courts.call_count, 2)
        self.assertEqual(
            get_courts.call_args_list[1].kwargs["court_name_prefix"],
            "风雨场",
        )
        publish.assert_called_once_with(
            "szw",
            "深圳湾",
            [
                {
                    "date": "2026-08-12",
                    "court_name": "1号场",
                    "start_time": "09:00",
                    "end_time": "10:00",
                },
                {
                    "date": "2026-08-12",
                    "court_name": "风雨场网球1号",
                    "start_time": "10:00",
                    "end_time": "11:00",
                },
            ],
            healthy=True,
            error=None,
        )

    def test_gba_publishes_an_independent_observation(self):
        class NoonDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 12, 12, 0, tzinfo=tz)

        with (
            patch.object(szw_watcher.datetime, "datetime", NoonDateTime),
            patch.object(
                szw_watcher,
                "get_free_tennis_court_infos_for_szw",
                return_value={},
            ) as get_courts,
            patch.object(szw_watcher, "publish_venue_observation") as publish,
        ):
            szw_watcher.check_and_notify_for_day(0, venue_key="gba")

        self.assertEqual(
            get_courts.call_args.kwargs["project_uuid"],
            "0ddda9c33d4e11f1b51c2273436a3e4e",
        )
        publish.assert_called_once_with(
            "gba",
            "大湾区网球场",
            [],
            healthy=True,
            error=None,
        )

    def test_crland_wechat_windows_keep_szw_and_change_gba_weekend_start(self):
        weekday = datetime.datetime(2026, 8, 17)
        weekend = datetime.datetime(2026, 8, 16)
        szw = szw_watcher.CRLAND_VENUES["szw"]
        gba = szw_watcher.CRLAND_VENUES["gba"]

        self.assertTrue(szw_watcher.slot_in_wechat_window(["18:00", "19:00"], weekday, szw))
        self.assertTrue(szw_watcher.slot_in_wechat_window(["20:00", "21:00"], weekday, gba))
        self.assertFalse(szw_watcher.slot_in_wechat_window(["21:00", "22:00"], weekday, gba))
        self.assertFalse(szw_watcher.slot_in_wechat_window(["12:00", "13:00"], weekday, gba))
        self.assertFalse(szw_watcher.slot_in_wechat_window(["22:00", "23:00"], weekday, gba))
        self.assertFalse(szw_watcher.slot_in_wechat_window(["12:00", "13:00"], weekend, szw))
        self.assertTrue(szw_watcher.slot_in_wechat_window(["12:00", "13:00"], weekend, gba))
        self.assertFalse(szw_watcher.slot_in_wechat_window(["21:00", "22:00"], weekend, gba))
        self.assertTrue(szw_watcher.slot_in_wechat_window(["16:00", "17:00"], weekend, szw))
        self.assertEqual(
            szw_watcher.find_available_slots([], {"start_time": "09:00", "end_time": "21:00"}),
            [["09:00", "21:00"]],
        )

    def test_gba_wechat_uses_shared_zacks_chatrooms_with_gba_hours(self):
        class WeekendNoon(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 16, 12, 0, tzinfo=tz)

        variables = {
            "SZW_API_AUTHORIZATION": make_szw_authorization(4_102_444_800),
            "SZ_TENNIS_CHATROOMS": "Zacks_A\nZacks_B",
            "大湾区网球场": [],
        }

        def get_variable(key, default=None, deserialize_json=False):
            return variables.get(key, default)

        def set_variable(key, value, description=None, serialize_json=False):
            variables[key] = value

        with (
            patch.object(szw_watcher.datetime, "datetime", WeekendNoon),
            patch.object(
                szw_watcher,
                "get_free_tennis_court_infos_for_szw",
                return_value={"1号场": [["10:00", "11:00"], ["12:00", "13:00"]]},
            ),
            patch.object(szw_watcher, "publish_venue_observation"),
            patch.object(szw_watcher.Variable, "get", side_effect=get_variable),
            patch.object(szw_watcher.Variable, "set", side_effect=set_variable),
            patch.object(szw_watcher, "send_wechat_text_to_chatrooms_best_effort") as send,
        ):
            szw_watcher.check_and_notify_for_day(0, venue_key="gba")

        send.assert_called_once()
        self.assertEqual(send.call_args.args[0], ["Zacks_A", "Zacks_B"])
        self.assertIn("12:00-13:00", send.call_args.args[1])
        self.assertNotIn("10:00-11:00", send.call_args.args[1])
        self.assertEqual(send.call_args.kwargs["source"], "大湾区网球场巡检")
        self.assertEqual(send.call_args.kwargs["booking_venue_id"], "gba")
        self.assertIn("【大湾区网球场1号场】", send.call_args.args[1])

    def test_szw_upstream_failure_is_published_and_fails_the_task(self):
        class NoonDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 8, 12, 12, 0, tzinfo=tz)

        with (
            patch.object(szw_watcher.datetime, "datetime", NoonDateTime),
            patch.object(
                szw_watcher,
                "get_free_tennis_court_infos_for_szw",
                side_effect=RuntimeError("upstream TLS failed"),
            ),
            patch.object(szw_watcher, "publish_venue_observation") as publish,
        ):
            with self.assertRaisesRegex(
                FakeAirflowFailException,
                "upstream TLS failed",
            ):
                szw_watcher.check_and_notify_for_day(0)

        publish.assert_called_once_with(
            "szw",
            "深圳湾",
            [],
            healthy=False,
            error="upstream TLS failed",
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


class CrlandAuthorizationRotationTest(unittest.TestCase):
    def setUp(self):
        self.minute = datetime.datetime(2026, 10, 19, 4, 0, tzinfo=datetime.UTC)
        self.now = self.minute.timestamp()
        self.authorizations = [
            make_szw_authorization(4_102_444_800, account=f"rotation-test-{index}")
            for index in range(3)
        ]
        FakeVariable.values = {
            "SZW_API_AUTHORIZATIONS": json.dumps(self.authorizations),
            "SZW_API_AUTHORIZATION": make_szw_authorization(4_102_444_800, account="legacy-test"),
        }

    def tearDown(self):
        FakeVariable.values = {}

    def test_three_consecutive_minutes_rotate_then_repeat(self):
        selected = [
            szw_watcher.select_crland_authorization(
                data_interval_end=self.minute + datetime.timedelta(minutes=offset),
                now=self.now,
            )
            for offset in range(7)
        ]
        self.assertEqual(selected, self.authorizations * 2 + self.authorizations[:1])

    def test_pool_normalizes_raw_tokens(self):
        pool = [authorization.removeprefix("Wechat ") for authorization in self.authorizations]
        self.assertEqual(
            szw_watcher.validate_szw_authorization_pool(json.dumps(pool), now=self.now),
            tuple(self.authorizations),
        )

    def test_airflow_minute_is_stable_for_delayed_execution_and_retries(self):
        for delay_seconds in (0, 70, 125, 420):
            with self.subTest(delay_seconds=delay_seconds):
                self.assertEqual(
                    szw_watcher.select_crland_authorization(
                        data_interval_end=self.minute,
                        logical_date=self.minute - datetime.timedelta(minutes=1),
                        now=self.now + delay_seconds,
                    ),
                    self.authorizations[0],
                )

    def test_logical_date_fallback_and_timezone_equivalence(self):
        for boundary in (
            self.minute,
            self.minute.replace(tzinfo=None),
            self.minute.astimezone(datetime.timezone(datetime.timedelta(hours=8))),
            self.minute.isoformat(),
        ):
            self.assertEqual(
                szw_watcher.select_crland_authorization(logical_date=boundary, now=self.now + 70),
                self.authorizations[0],
            )
        self.assertEqual(
            szw_watcher.select_crland_authorization(now=self.now + 70),
            self.authorizations[1],
        )

    def test_same_scheduled_minute_is_shared_across_venues_dates_and_areas(self):
        class NoonDateTime(datetime.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 10, 19, 12, 0, tzinfo=tz)

        clock = [self.now + 70]

        def fake_get_courts(*args, **kwargs):
            clock[0] += 61
            return {}

        logs = io.StringIO()
        with (
            patch.object(szw_watcher.datetime, "datetime", NoonDateTime),
            patch.object(szw_watcher.time, "time", side_effect=lambda: clock[0]),
            patch.object(
                szw_watcher, "get_free_tennis_court_infos_for_szw", side_effect=fake_get_courts
            ) as get_courts,
            patch.object(szw_watcher, "publish_venue_observation") as publish,
            patch.object(szw_watcher, "send_wechat_text_to_chatrooms_best_effort") as send,
            redirect_stdout(logs),
        ):
            for venue_key, day_count in (("szw", 4), ("gba", 3)):
                for day_offset in range(day_count):
                    szw_watcher.check_and_notify_for_day(
                        day_offset,
                        venue_key=venue_key,
                        data_interval_end=self.minute,
                        logical_date=self.minute - datetime.timedelta(minutes=1),
                    )

        self.assertEqual(get_courts.call_count, 11)
        self.assertEqual(
            {call.kwargs["authorization"] for call in get_courts.call_args_list},
            {self.authorizations[0]},
        )
        self.assertEqual(
            {call.args[0] for call in get_courts.call_args_list},
            {"2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22"},
        )
        self.assertEqual(
            {call.kwargs["field_area_uuid"] for call in get_courts.call_args_list},
            {
                szw_watcher.SZW_FIELD_AREA_UUID,
                szw_watcher.SZW_COVERED_FIELD_AREA_UUID,
                szw_watcher.GBA_FIELD_AREA_UUID,
            },
        )
        self.assertEqual(publish.call_count, 7)
        send.assert_not_called()
        self.assertEqual(
            logs.getvalue().count(
                "CRLand authorization: mode=rotation slot=1/3 "
                "round_minute_utc=2026-10-19T04:00+00:00"
            ),
            7,
        )
        for authorization in self.authorizations:
            self.assertNotIn(authorization, logs.getvalue())
        self.assertNotIn("rotation-test", logs.getvalue())

    def test_legacy_fallback_is_used_only_when_pool_is_missing(self):
        del FakeVariable.values["SZW_API_AUTHORIZATIONS"]
        self.assertEqual(
            szw_watcher.select_crland_authorization(now=self.now),
            FakeVariable.values["SZW_API_AUTHORIZATION"],
        )

    def test_malformed_expired_or_duplicate_pool_never_falls_back_or_calls_network(self):
        invalid_pools = {
            "empty": "",
            "malformed_json": "[unparseable",
            "null": "null",
            "object": "{}",
            "no_accounts": "[]",
            "two_accounts": json.dumps(self.authorizations[:2]),
            "four_accounts": json.dumps([*self.authorizations, self.authorizations[0]]),
            "non_string_account": json.dumps([*self.authorizations[:2], None]),
            "expired_account": json.dumps(
                [*self.authorizations[:2], make_szw_authorization(self.now - 1, "expired-test")]
            ),
            "duplicate_token": json.dumps([*self.authorizations[:2], self.authorizations[0]]),
            "duplicate_account": json.dumps(
                [
                    *self.authorizations[:2],
                    make_szw_authorization(
                        4_102_444_800, "duplicate-test", claims={"openid": "rotation-test-0"}
                    ),
                ]
            ),
            "missing_identity": json.dumps(
                [
                    *self.authorizations[:2],
                    make_szw_authorization(4_102_444_800, "", claims={"sub": None}),
                ]
            ),
        }
        for reason, value in invalid_pools.items():
            with self.subTest(reason=reason):
                FakeVariable.values["SZW_API_AUTHORIZATIONS"] = value
                with (
                    patch.object(szw_watcher, "create_crland_http_session") as session,
                    patch.object(
                        szw_watcher.Variable, "get", wraps=FakeVariable.get
                    ) as get_variable,
                    patch.object(szw_watcher.time, "time", return_value=self.now),
                    self.assertRaises(ValueError) as raised,
                ):
                    szw_watcher.get_free_tennis_court_infos_for_szw(
                        "2026-10-20", ["不使用代理"], {"start_time": "09:00", "end_time": "21:00"}
                    )
                session.assert_not_called()
                self.assertEqual(
                    [call.args[0] for call in get_variable.call_args_list],
                    ["SZW_API_AUTHORIZATIONS"],
                )
                for authorization in self.authorizations:
                    self.assertNotIn(authorization, str(raised.exception))
                self.assertNotIn("rotation-test", str(raised.exception))

    def test_jwt_shape_and_expiration_validation_rejects_unsafe_values(self):
        valid_token = self.authorizations[0]
        header, payload, signature = valid_token.removeprefix("Wechat ").split(".")
        invalid_tokens = {
            "newline": valid_token + "\n",
            "invalid_scheme": valid_token.replace("Wechat ", "Bearer "),
            "empty_segment": f"Wechat {header}..{signature}",
            "invalid_base64": f"Wechat {header}.{payload}!.{signature}",
            "invalid_header": f"Wechat {payload}.{payload}.{signature}",
            "non_object_payload": f"Wechat {header}.W10.{signature}",
            "invalid_signature": f"Wechat {header}.{payload}.short",
            "nan_expiration": make_szw_authorization(float("nan")),
            "infinite_expiration": make_szw_authorization(float("inf")),
            "boolean_expiration": make_szw_authorization(True),
            "past_expiration": make_szw_authorization(self.now - 1),
        }
        for reason, token in invalid_tokens.items():
            with self.subTest(reason=reason), self.assertRaises(ValueError):
                szw_watcher.validate_szw_authorization(token, now=self.now)

    def test_expiration_uses_execution_time_instead_of_historical_schedule(self):
        FakeVariable.values["SZW_API_AUTHORIZATIONS"] = json.dumps(
            [make_szw_authorization(self.now + 60, "expiring-test"), *self.authorizations[1:]]
        )
        with self.assertRaisesRegex(ValueError, "已过期"):
            szw_watcher.select_crland_authorization(
                data_interval_end=self.minute, now=self.now + 120
            )

    def test_invalid_schedule_never_silently_selects_a_wallclock_account(self):
        with self.assertRaisesRegex(ValueError, "调度时间格式非法"):
            szw_watcher.select_crland_authorization(data_interval_end="invalid", now=self.now)

    def test_retries_keep_one_account_when_request_crosses_minute(self):
        captured_authorizations = []
        clock = [self.now + 59]

        class FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, *args, **kwargs):
                captured_authorizations.append(kwargs["headers"]["Authorization"])
                clock[0] += 60
                return types.SimpleNamespace(
                    status_code=503 if len(captured_authorizations) < 3 else 200,
                    json=lambda: {"code": 200, "result": {"fieldList": [], "matrix": []}},
                )

        with (
            patch.object(szw_watcher, "create_crland_http_session", return_value=FakeSession()),
            patch.object(szw_watcher.time, "time", side_effect=lambda: clock[0]),
            patch.object(szw_watcher.time, "sleep"),
        ):
            self.assertEqual(
                szw_watcher.get_free_tennis_court_infos_for_szw(
                    "2026-10-20", ["不使用代理"], {"start_time": "09:00", "end_time": "21:00"}
                ),
                {},
            )
        self.assertEqual(captured_authorizations, [self.authorizations[0]] * 3)

    def test_authentication_failure_does_not_try_other_accounts_and_redacts_response(self):
        for http_status in (200, 401):
            with self.subTest(http_status=http_status):
                session = unittest.mock.MagicMock()
                session.__enter__.return_value = session
                session.post.return_value = types.SimpleNamespace(
                    status_code=http_status,
                    json=lambda: {"code": 401, "text": self.authorizations[1] + " rotation-test-1"},
                )
                logs = io.StringIO()
                with (
                    patch.object(szw_watcher, "create_crland_http_session", return_value=session),
                    patch.object(szw_watcher.time, "time", return_value=self.now + 61),
                    patch.object(szw_watcher.time, "sleep"),
                    redirect_stdout(logs),
                    self.assertRaisesRegex(Exception, "code=401") as raised,
                ):
                    szw_watcher.get_free_tennis_court_infos_for_szw(
                        "2026-10-20", ["不使用代理"], {"start_time": "09:00", "end_time": "21:00"}
                    )
                session.post.assert_called_once()
                self.assertEqual(
                    session.post.call_args.kwargs["headers"]["Authorization"],
                    self.authorizations[1],
                )
                self.assertNotIn(self.authorizations[1], logs.getvalue() + str(raised.exception))
                self.assertNotIn("rotation-test", logs.getvalue() + str(raised.exception))

    def test_transport_errors_cannot_expose_headers_or_account_identifiers(self):
        session = unittest.mock.MagicMock()
        session.__enter__.return_value = session
        session.post.side_effect = szw_watcher.requests.ConnectionError(
            self.authorizations[0] + " rotation-test-0"
        )
        logs = io.StringIO()
        with (
            patch.object(szw_watcher, "create_crland_http_session", return_value=session),
            patch.object(szw_watcher.time, "time", return_value=self.now),
            patch.object(szw_watcher.time, "sleep"),
            redirect_stdout(logs),
            self.assertRaisesRegex(Exception, "ConnectionError") as raised,
        ):
            szw_watcher.get_free_tennis_court_infos_for_szw(
                "2026-10-20", ["不使用代理"], {"start_time": "09:00", "end_time": "21:00"}
            )
        self.assertNotIn(self.authorizations[0], logs.getvalue() + str(raised.exception))
        self.assertNotIn("rotation-test", logs.getvalue() + str(raised.exception))


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

        messages = tops_watcher.build_new_notifications(
            data_list,
            sent_messages,
            current_year=2026,
        )

        self.assertEqual(
            messages,
            ["【TOPS科技园风雨棚1号场】星期一(06-08)空场: 19:00-20:00"],
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

    def test_check_tennis_courts_publishes_webapp_before_wechat_fallback(self):
        FakeVariable.values = {}
        expected_msg = "【TOPS科技园室外6号场】星期六(07-11)空场: 07:00-17:00"

        original_load_proxy = tops_watcher.load_proxy_list
        original_get_availability = tops_watcher.get_tennis_court_availability
        original_publish = tops_watcher.publish_venue_observation
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

        events = []
        observations = []
        wechat_calls = []

        def fake_publish(*args, **kwargs):
            events.append("webapp")
            observations.append((args, kwargs))
            return {"success": True}

        def fallback_wechat(msg):
            events.append("wechat")
            wechat_calls.append(msg)
            return [{"success": False, "error": "device_busy"}]

        tops_watcher.load_proxy_list = lambda: []
        tops_watcher.get_tennis_court_availability = fake_get_availability
        tops_watcher.publish_venue_observation = fake_publish
        tops_watcher.enqueue_wechat_message = fallback_wechat
        tops_watcher.datetime = FixedDatetimeModule

        try:
            tops_watcher.run_check_tennis_courts()

            self.assertIn(expected_msg, FakeVariable.values.get(tops_watcher.CACHE_KEY, []))
            self.assertEqual(events, ["webapp", "wechat"])
            self.assertEqual(observations[0][0][0:2], ("tops", "TOPS 科技园"))
            self.assertEqual(wechat_calls, [expected_msg])
        finally:
            tops_watcher.load_proxy_list = original_load_proxy
            tops_watcher.get_tennis_court_availability = original_get_availability
            tops_watcher.publish_venue_observation = original_publish
            tops_watcher.enqueue_wechat_message = original_enqueue
            tops_watcher.datetime = original_datetime


if __name__ == "__main__":
    unittest.main()
