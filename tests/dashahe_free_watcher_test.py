from __future__ import annotations

import hashlib
import sys
from datetime import date
from types import ModuleType
from unittest.mock import Mock, patch

import pytest

from wechat_airflow.venues import dashahe_free_watcher as watcher
from wechat_airflow.venues.nswtt_client import NswttConfig, encode_payload


def test_nswtt_signature_matches_upstream_protocol() -> None:
    key = "ABCDEFGHJKMNPQRSTWXYZabcdefhijkm"
    timestamp = 1_779_427_751_518
    plain_text = "paytype=1&projectid=project"

    encoded = encode_payload(plain_text, key=key, timestamp=timestamp)

    expected = hashlib.md5(  # noqa: S324 - protocol compatibility assertion
        f"{timestamp}@{key}@cGF5dHlwZT0xJnByb2plY3RpZD1wcm9qZWN0".encode()
    ).hexdigest()
    assert encoded.headers["X-APP-SIGN"] == expected
    assert encoded.headers["X-APP-TIMESTAMP"] == str(timestamp)


def test_config_requires_auth_without_exposing_it() -> None:
    with pytest.raises(ValueError, match="app_version and cookie"):
        NswttConfig.from_value({"app_version": "2.0"})

    config = NswttConfig.from_value(
        {
            "app_version": "2.14.30",
            "cookie": {"sid": "secret"},
            "timeout_seconds": 60,
        }
    )

    assert config.cookie == "sid=secret"
    assert config.timeout_seconds == 30


def test_ready_dates_require_calendar_sale_status() -> None:
    calendar = {
        "list": [
            {
                "slicedate": "2026-08-15",
                "status": 200,
                "openstatus": 200,
                "issale": 200,
            },
            {
                "slicedate": "2026-08-16",
                "status": 200,
                "openstatus": 200,
                "issale": 100,
            },
            {
                "slicedate": "2026-09-01",
                "status": 200,
                "openstatus": 200,
                "issale": 200,
            },
        ]
    }

    assert watcher.ready_free_dates(calendar, today=date(2026, 8, 15)) == ["2026-08-15"]


def test_extract_free_slots_requires_free_courts_for_the_date() -> None:
    exists, slots = watcher.extract_free_slots(
        "2026-08-16",
        {"placelist": [], "slicelist": []},
    )
    assert exists is False
    assert slots == []

    exists, slots = watcher.extract_free_slots(
        "2026-08-15",
        {
            "placelist": [{"id": "p1", "placename": "1号场"}],
            "slicelist": [
                {
                    "placeid": "p1",
                    "starttime": "18:00",
                    "endtime": "19:00",
                    "status": 200,
                    "finalunitpricey": 0,
                },
                {
                    "placeid": "p1",
                    "starttime": "19:00",
                    "endtime": "20:00",
                    "status": 200,
                    "finalunitpricey": 80,
                },
            ],
        },
    )
    assert exists is True
    assert slots == [
        {
            "date": "2026-08-15",
            "court_name": "1号场",
            "start_time": "18:00",
            "end_time": "19:00",
        }
    ]


def test_inspection_skips_unreleased_date_before_publishing() -> None:
    client = Mock()
    client.calendar_list.return_value = {
        "data": {
            "list": [
                {
                    "slicedate": date.today().isoformat(),
                    "status": 200,
                    "openstatus": 200,
                    "issale": 200,
                }
            ]
        }
    }
    client.slice_list.return_value = {"data": {"placelist": [], "slicelist": []}}

    with (
        patch.object(
            watcher, "_load_config_value", return_value={"app_version": "v", "cookie": "sid=x"}
        ),
        patch.object(watcher, "NswttClient", return_value=client),
        patch.object(watcher, "publish_venue_observation") as publish,
        patch.object(watcher, "_load_cache", return_value=[]),
        patch.object(watcher, "send_wechat_text_to_chatrooms_best_effort") as send,
    ):
        result = watcher.run_check_dashahe_free_courts()

    assert result["free_dates"] == []
    assert result["available_slot_count"] == 0
    publish.assert_called_once_with(
        "dsh_free",
        "大沙河免费场",
        [],
        healthy=True,
        error=None,
    )
    send.assert_not_called()


def test_format_wechat_messages_uses_venue_and_weekday() -> None:
    messages = watcher.format_wechat_messages(
        [
            {
                "date": "2026-08-16",
                "court_name": "1号场",
                "start_time": "18:00",
                "end_time": "19:00",
            }
        ]
    )
    assert messages == ["【大沙河免费场1号场】星期日(08-16)空场: 18:00-19:00"]


def test_wechat_notifies_only_the_dashah_free_group_after_cache_write() -> None:
    client = Mock()
    today = date.today().isoformat()
    client.calendar_list.return_value = {
        "data": {
            "list": [
                {
                    "slicedate": today,
                    "status": 200,
                    "openstatus": 200,
                    "issale": 200,
                }
            ]
        }
    }
    client.slice_list.return_value = {
        "data": {
            "placelist": [{"id": "p1", "placename": "1号场"}],
            "slicelist": [
                {
                    "placeid": "p1",
                    "starttime": "18:00",
                    "endtime": "19:00",
                    "status": 200,
                    "finalunitpricey": 0,
                }
            ],
        }
    }
    stored: list[list[str]] = []

    with (
        patch.object(
            watcher, "_load_config_value", return_value={"app_version": "v", "cookie": "sid=x"}
        ),
        patch.object(watcher, "NswttClient", return_value=client),
        patch.object(watcher, "publish_venue_observation") as publish,
        patch.object(watcher, "_load_cache", return_value=[]),
        patch.object(watcher, "_store_cache", side_effect=lambda cache: stored.append(list(cache))),
        patch.object(watcher, "send_wechat_text_to_chatrooms_best_effort") as send,
    ):
        watcher.run_check_dashahe_free_courts()

    assert publish.called
    assert send.called
    assert send.call_args.args[0] == ["Zacks_大沙河限定免费"]
    assert "18:00-19:00" in send.call_args.args[1]
    assert send.call_args.kwargs["source"] == "大沙河免费场巡检"
    assert send.call_args.kwargs["booking_venue_id"] == "dsh_free"
    assert stored
    assert publish.call_args.args[0] == "dsh_free"
    assert send.call_count == 1


def test_load_cache_creates_empty_variable_when_missing() -> None:
    stored: list[object] = []
    airflow = ModuleType("airflow")
    sdk = ModuleType("airflow.sdk")

    class FakeVariable:
        @staticmethod
        def get(_key, deserialize_json=False, default=None):
            return default

        @staticmethod
        def set(key, value, description="", serialize_json=False):
            stored.append(value)

    sdk.Variable = FakeVariable
    airflow.sdk = sdk

    with patch.dict(sys.modules, {"airflow": airflow, "airflow.sdk": sdk}):
        cache = watcher._load_cache()

    assert cache == []
    assert stored == [[]]


def test_wechat_skips_already_cached_dashah_messages() -> None:
    client = Mock()
    today = date(2026, 8, 16)
    message = "【大沙河免费场1号场】星期日(08-16)空场: 18:00-19:00"
    client.calendar_list.return_value = {
        "data": {
            "list": [
                {
                    "slicedate": today.isoformat(),
                    "status": 200,
                    "openstatus": 200,
                    "issale": 200,
                }
            ]
        }
    }
    client.slice_list.return_value = {
        "data": {
            "placelist": [{"id": "p1", "placename": "1号场"}],
            "slicelist": [
                {
                    "placeid": "p1",
                    "starttime": "18:00",
                    "endtime": "19:00",
                    "status": 200,
                    "finalunitpricey": 0,
                }
            ],
        }
    }

    with (
        patch.object(
            watcher, "_load_config_value", return_value={"app_version": "v", "cookie": "sid=x"}
        ),
        patch.object(watcher, "NswttClient", return_value=client),
        patch.object(watcher, "publish_venue_observation"),
        patch.object(watcher, "_load_cache", return_value=[message]),
        patch.object(watcher, "_store_cache") as store,
        patch.object(watcher, "send_wechat_text_to_chatrooms_best_effort") as send,
        patch.object(watcher, "ready_free_dates", return_value=[today.isoformat()]),
    ):
        watcher.run_check_dashahe_free_courts()

    store.assert_not_called()
    send.assert_not_called()
