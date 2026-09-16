from __future__ import annotations

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "compare", Path(__file__).resolve().parents[1] / "scripts/ydmap_source_compare.py"
)
assert SPEC and SPEC.loader
compare = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare)


def test_source_identity_rejects_cross_product_and_cross_host():
    indoor = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317"
    assert compare.source_matches(indoor, "indoor")
    assert not compare.source_matches(indoor, "outdoor")
    assert not compare.source_matches(indoor.replace("bawtt", "wxsports"), "indoor")
    assert not compare.source_matches(indoor + "&salesItemId=103224", "indoor")


def test_resource_diagnostics_never_include_queries_or_other_hosts():
    assert (
        compare.public_resource("https://bawtt.ydmap.cn/js/app.js?token=private", "bawtt.ydmap.cn")
        == "/js/app.js"
    )
    assert compare.public_resource("https://other.example/js/app.js", "bawtt.ydmap.cn") is None
    assert compare.public_resource("https://bawtt.ydmap.cn/api/account", "bawtt.ydmap.cn") is None


def test_redaction_bounds_output():
    result = compare.redact(
        "https://example.test?token=private person@example.test token=secretvalue " + "a" * 80
    )
    assert "secretvalue" not in result
    assert "person@" not in result
    assert "private" not in result
    assert len(compare.redact("hello " * 2000)) <= 3500


def test_production_browser_never_reused_and_no_spoofing():
    text = (Path(__file__).resolve().parents[1] / "scripts/ydmap_source_compare.py").read_text()
    for forbidden in (
        "/tmp/dsh_ydmap_profile",
        "pkill",
        "--no-sandbox",
        "--user-agent=",
        "AutomationControlled",
        "Object.defineProperty",
        "get_cookies",
        "--dump-config",
    ):
        assert forbidden not in text
    assert "port == 9224" in text
    assert 'bookabilityVerified": False' in text
