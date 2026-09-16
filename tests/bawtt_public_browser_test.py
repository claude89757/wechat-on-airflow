import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("bawtt_public", Path(__file__).resolve().parents[1] / "scripts/probe_bawtt_public_browser.py")
assert SPEC and SPEC.loader
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def test_no_private_field_values_are_exported():
    result = probe.field_summary({"token": "private-token", "customerName": "private-name", "phone": 12345678901, "orderId": 8765, "venueName": "1号场", "status": 1, "className": "disabled"})
    assert "private" not in str(result)
    assert "12345678901" not in str(result)
    assert "8765" not in str(result)
    assert result["status"]["value"] == 1
    assert result["venueName"]["value"] == "1号场"


def test_api_allowlist_requires_exact_origin_path():
    url = "https://bawtt.ydmap.cn/srv100244/api/pub/sport/venue/getVenueOrderList"
    assert probe.api_name(url) == "getVenueOrderList"
    assert probe.api_name(url.replace("bawtt.ydmap.cn", "other.example")) is None
    assert probe.api_name(url.replace("getVenueOrderList", "createOrder")) is None
    assert probe.api_name(url.replace("https:", "http:")) is None


def test_opaque_and_network_values_are_omitted():
    for value in ("https://example.invalid/?token=abc", "a" * 60, "person@example.invalid"):
        assert "value" not in probe.field_summary(value, "venueName")


def test_schema_is_bounded_and_no_bookability_is_invented():
    assert len(probe.field_summary([{"status": 1}] * 100)["sample"]) == 3
    assert probe.field_summary("not-a-date", "curDate") == {"type": "str"}
    assert probe.field_summary("2026-09-16", "curDate")["value"] == "2026-09-16"
