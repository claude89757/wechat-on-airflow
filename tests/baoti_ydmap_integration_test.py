"""Bao'an protocol and notification regressions; all inputs and I/O are synthetic."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
import shlex
import subprocess
import sys
import types
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest

from wechat_airflow.host_core.wechat_queue import current_message
from wechat_airflow.notifications import webapp, wechat

airflow = types.ModuleType("airflow")
sdk = types.ModuleType("airflow.sdk")
sdk.Variable = SimpleNamespace
sys.modules.setdefault("airflow", airflow)
sys.modules.setdefault("airflow.sdk", sdk)
client = importlib.import_module("wechat_airflow.venues.baoti_ydmap_client")
watcher = importlib.import_module("wechat_airflow.venues.baoti_ydmap_watcher")

DATES = {"2026-10-30", "2026-10-31"}
NOTICE = "【宝安网球中心·室外场1号】星期六(10-31)空场: 11:00-12:00"


def proven_payload():
    groups = [
        ("outdoor", "111317", "室外", "室外场1号"),
        ("indoor", "103224", "室内", "室内A号场"),
        ("windrain", "111319", "风雨", "风雨场1号"),
    ]
    return {
        "schema_version": 2,
        "venue": "baoti",
        "ok": True,
        "captcha": False,
        "days": [
            {
                "date": day,
                "courts": {"室外场1号": [["11:00", "12:00"]]} if day == "2026-10-31" else {},
                "groups": [
                    {
                        "key": key,
                        "sales_item_id": product,
                        "source_host": "bawtt.ydmap.cn",
                        "source_sales_id": "104036",
                        "freshness": "both_source_arrays_replaced_after_date_selection",
                        "load_generation": 2,
                        "data_version": {"platforms": 3, "orders": 4},
                        "product_name": label + "网球场",
                        "source_date": day,
                        "selected_date": day,
                        "court_names": [court],
                        "cell_count": 24,
                    }
                    for key, product, label, court in groups
                ],
            }
            for day in sorted(DATES)
        ],
    }


@pytest.fixture
def configured_watcher(monkeypatch):
    values = {}
    variable = SimpleNamespace(
        get=lambda key, default=None, **kwargs: values.get(key, default),
        set=lambda key, value, **kwargs: values.__setitem__(key, value),
    )
    monkeypatch.setattr(watcher, "Variable", variable)
    monkeypatch.setattr(watcher, "_load_device_config", lambda: None)
    monkeypatch.setattr(
        watcher, "_local_now", lambda: datetime(2026, 10, 30, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    monkeypatch.setattr(watcher, "fetch_inspect_payload", lambda *args, **kwargs: proven_payload())
    publish = Mock(return_value={"success": True})
    enqueue = Mock()
    monkeypatch.setattr(watcher, "publish_venue_observation", publish)
    monkeypatch.setattr(watcher, "enqueue_wechat_message", enqueue)
    return values, publish, enqueue


def test_real_shell_receives_full_query_and_returns_curl_error(monkeypatch):
    execute = Mock(return_value=(json.dumps(proven_payload()), "", 0))
    monkeypatch.setattr(client, "exec_pi_command", execute)
    config = SimpleNamespace(
        scrape_url="http://127.0.0.1:8788/inspect",
        host="unused",
        port=1,
        username="unused",
        password="synthetic",
        host_key_sha256="unused",
    )
    client.fetch_inspect_payload(config)
    command = execute.call_args.args[5]
    assert execute.call_args.kwargs["timeout_seconds"] > client.SCRAPE_TIMEOUT_SECONDS
    # The shell function shadows curl completely, so this cannot make a request.
    completed = subprocess.run(
        ["/bin/sh", "-c", 'curl() { printf "%s\\n" "$@"; return 7; }; ' + command],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert completed.returncode == 7
    assert completed.stdout.splitlines()[-1] == ("http://127.0.0.1:8788/inspect?venue=baoti&days=2")
    config.scrape_url += "?venue=dsh&days=5&mode=normal"
    client.fetch_inspect_payload(config)
    url = shlex.split(execute.call_args.args[5])[-1]
    assert parse_qs(urlsplit(url).query) == {"venue": ["baoti"], "days": ["2"], "mode": ["normal"]}


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": None},
        {"schema_version": 1},
        {"schema_version": 2.0},
        {"venue": None},
        {"venue": "dsh"},
        {"ok": False},
        {"captcha": True},
    ],
)
def test_old_or_wrong_venue_payload_is_rejected(change):
    payload = proven_payload()
    payload.update(change)
    with pytest.raises(ValueError):
        client.parse_inspect_payload(payload, expected_dates=DATES)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_date", "2026-10-29"),
        ("selected_date", "2026-10-29"),
        ("sales_item_id", "111319"),
        ("source_host", "wxsports.ydmap.cn"),
        ("source_sales_id", "100220"),
        ("freshness", None),
        ("load_generation", 0),
        ("load_generation", True),
        ("data_version", {"platforms": 3}),
        ("data_version", {"platforms": 0, "orders": 4}),
        ("product_name", "室内网球场"),
        ("cell_count", 0),
        ("cell_count", True),
        ("court_names", []),
    ],
)
def test_incomplete_or_mismatched_group_evidence_is_rejected(field, value):
    payload = proven_payload()
    payload["days"][0]["groups"][0][field] = value
    with pytest.raises(ValueError):
        client.parse_inspect_payload(payload, expected_dates=DATES)


def test_missing_date_or_product_cannot_be_published_as_complete():
    payload = proven_payload()
    payload["days"].pop()
    with pytest.raises(ValueError, match="date coverage"):
        client.parse_inspect_payload(payload, expected_dates=DATES)
    payload = proven_payload()
    payload["days"][0]["groups"].pop()
    with pytest.raises(ValueError, match="incomplete"):
        client.parse_inspect_payload(payload, expected_dates=DATES)


@pytest.mark.parametrize(
    "courts",
    [
        {"大沙河1号场": [["11:00", "12:00"]]},
        {"室外场1号": [["bad", "12:00"]]},
        {"室外场1号": [["11:00"]]},
    ],
)
def test_unproven_court_or_malformed_slot_is_rejected(courts):
    payload = proven_payload()
    payload["days"][1]["courts"] = courts
    with pytest.raises(ValueError):
        client.parse_inspect_payload(payload, expected_dates=DATES)


def test_empty_availability_with_all_three_loaded_grids_is_valid():
    payload = proven_payload()
    for day in payload["days"]:
        day["courts"] = {}
    assert client.parse_inspect_payload(payload, expected_dates=DATES) == {
        "2026-10-30": {},
        "2026-10-31": {},
    }


def test_midnight_end_and_next_year_weekday_remain_correct():
    data = watcher.filter_court_data_for_notification(
        "2027-01-01", {"室外场1号": [["23:00", "24:00"]]}
    )
    assert watcher.build_new_notifications(data, []) == [
        "【宝安网球中心·室外场1号】星期五(01-01)空场: 23:00-24:00"
    ]


def test_watcher_message_passes_real_queue_validator(configured_watcher):
    values, publish, enqueue = configured_watcher
    watcher.run_check_tennis_courts()
    message = enqueue.call_args.args[0]
    assert message == NOTICE
    slots = [
        {
            "booking_date": date(2026, 10, 31),
            "court_name": "室外场1号",
            "start_time": "11:00",
            "end_time": "12:00",
            "event_key": "synthetic-event",
        }
    ]
    assert current_message(message, slots) == (NOTICE, ["synthetic-event"], [])
    assert publish.call_args.kwargs["healthy"] is True
    assert values["宝安网球中心"] == [NOTICE]


def test_failed_observation_ack_never_preclaims_or_enqueues(configured_watcher):
    values, publish, enqueue = configured_watcher
    publish.return_value = {"success": False}
    watcher.run_check_tennis_courts()
    enqueue.assert_not_called()
    assert "宝安网球中心" not in values


def test_legacy_dsh_response_only_publishes_unhealthy_empty(configured_watcher, monkeypatch):
    _, publish, enqueue = configured_watcher
    payload = proven_payload()
    del payload["schema_version"]
    del payload["venue"]
    payload["venue_name"] = "大沙河国际网球交流中心"
    monkeypatch.setattr(watcher, "fetch_inspect_payload", lambda *args, **kwargs: payload)
    watcher.run_check_tennis_courts()
    enqueue.assert_not_called()
    publish.assert_called_once_with("baoti", "宝安网球中心", [], healthy=False, error="ValueError")


@pytest.mark.parametrize("available", [True, False])
def test_actual_scraper_payload_reaches_watcher_and_queue_with_verified_identity(
    available, configured_watcher, monkeypatch
):
    spec = importlib.util.spec_from_file_location(
        "baoti_pi_test_support", Path(__file__).with_name("pi_baoti_scraper_test.py")
    )
    assert spec is not None and spec.loader is not None
    pi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pi)

    # Execute the production scraper and parser, replacing only browser/device
    # boundaries. All date changes run through its real freshness validator.
    server = pi.load_server()
    clock = pi.Clock()
    driver = pi.FakeDriver()
    snapshots = iter(
        [
            pi.snapshot(day, generation, key=key, available=available)
            for key in ("outdoor", "indoor", "windrain")
            for day, generation in ((pi.TODAY, 1), (pi.TOMORROW, 2), (pi.TODAY, 3))
        ]
    )
    monkeypatch.setattr(server, "datetime", pi.FixedDatetime)
    monkeypatch.setattr(
        server, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep)
    )
    monkeypatch.setattr(server, "_cleanup_stale_browser", lambda: None)
    monkeypatch.setattr(server, "_start_chromium", lambda url: object())
    monkeypatch.setattr(server, "_wait_devtools", lambda timeout: None)
    monkeypatch.setattr(server, "_attach", lambda **kwargs: driver)
    monkeypatch.setattr(server, "_extract_day", lambda driver: next(snapshots))
    monkeypatch.setattr(server, "_stop", Mock())
    payload = server.scrape_available_slots("baoti", 2)
    assert payload["ok"] is True, json.dumps(payload, ensure_ascii=False)
    dates = {pi.TODAY.isoformat(), pi.TOMORROW.isoformat()}
    parsed = client.parse_inspect_payload(payload, expected_dates=dates)
    assert set(parsed) == dates
    assert driver.clicked == ["11-02", "11-01"] * 3

    values, publish, enqueue = configured_watcher
    monkeypatch.setattr(watcher, "fetch_inspect_payload", lambda *args, **kwargs: payload)
    monkeypatch.setattr(
        watcher,
        "_local_now",
        lambda: datetime(2026, 11, 1, 9, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    watcher.run_check_tennis_courts()
    assert publish.call_args.args[:2] == ("baoti", "宝安网球中心")
    assert publish.call_args.kwargs["healthy"] is True
    slots = publish.call_args.args[2]
    if not available:
        assert slots == []
        enqueue.assert_not_called()
        assert "宝安网球中心" not in values
        return
    assert len(slots) == 6
    assert {slot["date"] for slot in slots} == dates
    assert {slot["court_name"] for slot in slots} == {"室外场1号", "室内A号场", "风雨场1号"}
    current = [
        {
            "booking_date": date.fromisoformat(slot["date"]),
            "court_name": slot["court_name"],
            "start_time": slot["start_time"],
            "end_time": slot["end_time"],
            "event_key": f"synthetic-{index}",
        }
        for index, slot in enumerate(slots)
    ]
    message = enqueue.call_args.args[0]
    retained, event_keys, rejected = current_message(message, current)
    assert set(retained.splitlines()) == set(message.splitlines())
    assert len(event_keys) == 6
    assert rejected == []
    assert "预定入口" not in message


@pytest.mark.parametrize("outcome", ["network", "no_subscription", "paused", "stale_line"])
def test_unsent_preclaim_is_released_for_the_next_poll(outcome, monkeypatch):
    unrelated = "another successfully queued notification"
    cache = {
        "宝安网球中心": [NOTICE, unrelated],
        "SZ_TENNIS_CHATROOMS": "isolated-group" if outcome == "paused" else "",
        "WECHAT_SEND_DEVICE_NAME": "isolated-device",
    }
    monkeypatch.setattr(webapp, "_host_token", lambda: "synthetic")
    monkeypatch.setattr(
        wechat, "_get_variable", lambda key, default=None, **kwargs: cache.get(key, default)
    )
    monkeypatch.setattr(
        wechat, "_set_variable", lambda key, value, **kwargs: cache.__setitem__(key, value)
    )
    response = Mock()
    response.json.return_value = (
        {"success": True, "queued": 1, "rejected_lines": [NOTICE]}
        if outcome == "stale_line"
        else {"success": True, "queued": 0, "suppressed": True}
    )
    post = Mock(
        return_value=response,
        side_effect=RuntimeError("isolated failure") if outcome == "network" else None,
    )
    monkeypatch.setattr(wechat.requests, "post", post)
    wechat.send_wechat_text_to_chatrooms_best_effort(
        ["isolated-group"], NOTICE, booking_venue_id="baoti"
    )
    if outcome == "paused":
        post.assert_not_called()
    assert cache["宝安网球中心"] == [unrelated]
    data = watcher.filter_court_data_for_notification(
        "2026-10-31", {"室外场1号": [["11:00", "12:00"]]}
    )
    assert watcher.build_new_notifications(data, copy.deepcopy(cache["宝安网球中心"])) == [NOTICE]
