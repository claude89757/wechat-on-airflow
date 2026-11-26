from __future__ import annotations

import ast
import dataclasses
import datetime as real_datetime
import importlib
import sys
import types
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]


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


def _install_import_stubs() -> None:
    sdk = types.ModuleType("airflow.sdk")
    sdk.Variable = FakeVariable  # type: ignore[attr-defined]
    sys.modules.setdefault("airflow", types.ModuleType("airflow"))
    sys.modules.setdefault("airflow.sdk", sdk)


_install_import_stubs()
booking_links = importlib.import_module("wechat_airflow.notifications.booking_links")
ftty = importlib.import_module("wechat_airflow.venues.ftty_ydmap_watcher")
baoti = importlib.import_module("wechat_airflow.venues.baoti_ydmap_watcher")

SSH = {
    "host": "203.0.113.10",
    "port": 6000,
    "username": "pi-user",
    "password": "secret",
    "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
}


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    FakeVariable.values = {"PI_DEVICE_SSH": dict(SSH), "SZ_TENNIS_CHATROOMS": "Zacks_网球场"}
    monkeypatch.setattr(ftty, "Variable", FakeVariable)
    state: dict[str, Any] = {
        "published": [],
        "sent": [],
        "fetches": [],
        "payload": None,
        "proxies": ["36.147.78.166:443"],
    }

    def fake_fetch(
        config: object,
        *,
        days: int,
        venue: str,
        proxies: list[str] | None = None,
    ) -> object:
        state["fetches"].append({"days": days, "venue": venue, "proxies": proxies})
        if isinstance(state["payload"], Exception):
            raise state["payload"]
        return state["payload"]

    def fake_publish(*args: object, **kwargs: object) -> dict[str, bool]:
        state["published"].append((args, kwargs))
        return {"success": True}

    def fake_send(chatrooms: list[str], message: str, **kwargs: object) -> object:
        state["sent"].append((chatrooms, message, kwargs))
        return {"success": True}

    monkeypatch.setattr(ftty, "fetch_inspect_payload", fake_fetch)
    monkeypatch.setattr(ftty, "publish_venue_observation", fake_publish)
    monkeypatch.setattr(ftty, "send_wechat_text_to_chatrooms_best_effort", fake_send)
    monkeypatch.setattr(
        baoti,
        "BAOTI",
        dataclasses.replace(baoti.BAOTI, proxy_provider=lambda: list(state["proxies"])),
    )
    return state


def _at(monkeypatch: pytest.MonkeyPatch, hour: int, minute: int = 1) -> None:
    monkeypatch.setattr(
        ftty,
        "_local_now",
        lambda: real_datetime.datetime(2026, 11, 27, hour, minute, tzinfo=ftty.LOCAL_TIMEZONE),
    )


def test_baoti_dag_wiring_and_odd_minute_separation() -> None:
    tree = ast.parse(
        (ROOT / "dags/tennis_dags/sz_tennis/baoti_ydmap_watcher.py").read_text(encoding="utf-8")
    )
    calls = {
        node.func.id: node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    dag = calls["DAG"]
    assert ast.literal_eval(dag.args[0]) == "宝安网球中心巡检"
    dag_options = {keyword.arg: keyword.value for keyword in dag.keywords}
    cron = ast.literal_eval(dag_options["schedule"])
    assert cron == "1-59/5 * * * *"
    operator = {keyword.arg: keyword.value for keyword in calls["PythonOperator"].keywords}
    assert ast.literal_eval(operator["pool"]) == "ydmap_baoti_browser"
    assert operator["python_callable"].id == "run_check_tennis_courts"  # type: ignore[attr-defined]

    # Odd minutes never overlap with Dashah / Futian even-minute runs.
    odd_minutes = set(range(1, 60, 2))
    assert odd_minutes.isdisjoint(set(range(0, 60, 2)))


def test_before_0800_publishes_empty_for_slot_scope_without_scraping(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 7, 59)
    slot = real_datetime.datetime(2026, 11, 26, 23, 59, tzinfo=real_datetime.UTC)
    monkeypatch.setattr(ftty, "_run_slot", lambda: slot)
    expected_product = ftty.product_for(baoti.BAOTI, slot)
    assert expected_product is not None

    baoti.run_check_tennis_courts()
    assert harness["fetches"] == []
    assert harness["published"] == [
        (
            ("baoti", "宝安网球中心", []),
            {"healthy": True, "observation_scope": expected_product.observation_scope},
        )
    ]
    assert harness["sent"] == []


def test_rotates_three_products_across_consecutive_five_minute_ticks(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 9, 1)
    harness["payload"] = {"ok": True, "days": []}
    seen_venues: list[str] = []
    seen_scopes: list[str | None] = []
    base = real_datetime.datetime(2026, 11, 27, 1, 1, tzinfo=real_datetime.UTC)
    for step in range(3):
        slot = base + real_datetime.timedelta(minutes=5 * step)
        monkeypatch.setattr(ftty, "_run_slot", lambda s=slot: s)
        baoti.run_check_tennis_courts()
        seen_venues.append(harness["fetches"][-1]["venue"])
        seen_scopes.append(harness["published"][-1][1]["observation_scope"])

    assert set(seen_venues) == {"baoti_outdoor", "baoti_indoor", "baoti_covered"}
    assert set(seen_scopes) == {"outdoor", "indoor", "covered"}
    assert all(item["proxies"] == ["36.147.78.166:443"] for item in harness["fetches"])


def test_late_start_skips_baoti_only_after_three_minute_grace(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 9, 1)
    harness["payload"] = {"ok": True, "days": []}
    monkeypatch.setattr(ftty, "_late_start", lambda: real_datetime.timedelta(seconds=150))
    baoti.run_check_tennis_courts()
    assert len(harness["fetches"]) == 1
    assert len(harness["published"]) == 1

    # Beyond 180s skips stale catch-up runs.
    monkeypatch.setattr(ftty, "_late_start", lambda: real_datetime.timedelta(seconds=190))
    baoti.run_check_tennis_courts()
    assert len(harness["fetches"]) == 1
    assert len(harness["published"]) == 1


def test_fetch_baoti_proxies_filters_invalid_and_falls_back_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResp:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            pass

    raw = "\n".join(
        [
            "127.0.0.1:8080",
            "10.0.0.1:8080",
            "not-a-proxy",
            "36.147.78.166:443",
            "36.147.78.166:443",
            "101.251.204.174:8080",
        ]
    )
    captured: list[dict[str, object]] = []

    def fake_get(*args: object, **kwargs: object) -> FakeResp:
        captured.append(dict(kwargs))
        return FakeResp(raw)

    monkeypatch.setattr(baoti.requests, "get", fake_get)
    assert baoti.fetch_baoti_proxies() == ["36.147.78.166:443", "101.251.204.174:8080"]
    assert captured[0]["headers"] == {"Cache-Control": "no-cache", "Pragma": "no-cache"}

    def fail(*args: object, **kwargs: object) -> object:
        raise RuntimeError("network down")

    monkeypatch.setattr(baoti.requests, "get", fail)
    assert baoti.fetch_baoti_proxies() == []


def test_baoti_publishes_scope_and_notifies_wechat_with_booking_link(
    harness: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    _at(monkeypatch, 10, 1)
    slot = real_datetime.datetime(2026, 11, 27, 2, 1, tzinfo=real_datetime.UTC)
    monkeypatch.setattr(ftty, "_run_slot", lambda: slot)
    product = ftty.product_for(baoti.BAOTI, slot)
    assert product is not None

    harness["payload"] = {
        "ok": True,
        "days": [
            {"date": "2026-11-27", "courts": {"风雨场1号": [["18:00", "19:00"]]}},
            {"date": "2026-11-28", "courts": {}},
        ],
    }
    baoti.run_check_tennis_courts()
    args, kwargs = harness["published"][0]
    assert args[:2] == ("baoti", "宝安网球中心")
    assert kwargs == {"healthy": True, "observation_scope": product.observation_scope}
    chatrooms, message, options = harness["sent"][0]
    assert chatrooms == ["Zacks_网球场"]
    assert message == "【宝安网球中心风雨场1号】星期五(11-27)空场: 18:00-19:00"
    assert options == {"source": "宝安网球中心巡检", "booking_venue_id": "baoti"}
    program = booking_links.program_for_venue("baoti")
    assert program is not None
    assert parse_qs(urlparse(program.link).query)["salesItemId"] == ["111317"]
