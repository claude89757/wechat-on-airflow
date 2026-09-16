from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "bawtt_live", Path(__file__).parents[1] / "scripts/bawtt_live_query.py"
)
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@pytest.mark.parametrize("kind,product", [("indoor", "111317"), ("outdoor", "103224")])
def test_source_identity(kind: str, product: str) -> None:
    url = f"https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId={product}"
    assert probe.source_matches(url, kind)
    assert not probe.source_matches(url + "&salesItemId=123", kind)
    assert not probe.source_matches(url.replace("104036", "100220"), kind)
    other = "outdoor" if kind == "indoor" else "indoor"
    assert not probe.source_matches(url, other)


@pytest.mark.parametrize("path", ["getVenueOrderList", "getVenueCalendarList", "getSalesItemList"])
def test_query_allowlist(path: str) -> None:
    url = f"https://bawtt.ydmap.cn/srv100244/api/pub/sport/venue/{path}"
    assert probe.query_path(url + "?token=do-not-copy") == url.split(".cn", 1)[1]
    assert probe.query_path(url.replace("bawtt.ydmap.cn", "evil.example")) is None
    assert probe.query_path(url.replace(path, "createOrder")) is None


def test_schema_omits_private_values() -> None:
    raw = {
        "code": 0,
        "data": {
            "userName": "private",
            "phone": "12345678901",
            "cookie": "secret",
            "orderId": "opaque",
            "venueName": "1号场",
            "status": 1,
            "unknownValue": "private-description",
        },
    }
    encoded = json.dumps(probe.shape(raw), ensure_ascii=False)
    assert "private" not in encoded and "secret" not in encoded
    assert "12345678901" not in encoded and "opaque" not in encoded
    assert "1号场" in encoded
    assert probe.shape(raw)["data"]["status"] == 1


def test_schema_bounds_sample_size() -> None:
    value = probe.shape([{"status": 1}] * 100)
    assert value["length"] == 100
    assert len(value["items"]) == 2


def test_challenge_stops_before_query_body_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    class Browser:
        current_url = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=103224"

        def get_log(self, _):
            return []

        def get(self, _):
            pass

        def execute_script(self, _):
            return {"challenge": True, "loginRequired": False}

    def forbidden(*args):
        raise AssertionError("Must not continue after a challenge")

    monkeypatch.setattr(probe, "read_queries", forbidden)
    assert probe.observe(Browser(), "outdoor")["state"] == "human_verification_required"


@pytest.mark.parametrize(
    "text",
    [
        "token=some-private-value",
        "https://bawtt.ydmap.cn/page?token=some-private-value",
        "Cookie: some-private-value",
        "some-private-value@example.com",
    ],
)
def test_public_diagnostics_remove_credentials(text: str) -> None:
    assert "some-private-value" not in probe.public_text(text)


def test_public_diagnostics_preserve_error_messages() -> None:
    assert (
        probe.public_text("TypeError: WebAssembly is undefined")
        == "TypeError: WebAssembly is undefined"
    )
    assert len(probe.public_text("错误" * 1000)) <= 600


@pytest.mark.parametrize("visibility,expected_focus", [("visible", 0), ("hidden", 1)])
def test_focuses_only_hidden_normal_window(
    monkeypatch: pytest.MonkeyPatch, visibility: str, expected_focus: int
) -> None:
    class Browser:
        current_url = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=103224"
        focus_calls = 0

        def get_log(self, _):
            return []

        def get(self, _):
            pass

        def execute_script(self, script):
            if script == probe.BOOTSTRAP_JS:
                return [{"name": "App", "dataFields": []}]
            return {
                "challenge": False,
                "loginRequired": False,
                "visibility": visibility,
                "tableFound": False,
                "cells": 0,
            }

        def execute_cdp_cmd(self, method, params):
            assert method == "Page.bringToFront" and params == {}
            self.focus_calls += 1
            return {}

    browser = Browser()
    moments = iter([0, 46])
    monkeypatch.setattr(probe.time, "monotonic", lambda: next(moments))
    result = probe.observe(browser, "outdoor")
    assert browser.focus_calls == expected_focus
    assert result["state"] == "query_acquisition_incomplete"
    assert result["queries"] == []
    assert result["bootstrapComponents"] == [{"name": "App", "dataFields": []}]
