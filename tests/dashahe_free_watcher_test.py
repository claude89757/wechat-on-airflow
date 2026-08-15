from __future__ import annotations

import hashlib
from datetime import date
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
