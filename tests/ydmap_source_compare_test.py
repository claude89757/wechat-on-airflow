from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

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


def test_empty_table_component_does_not_pass():
    assert (
        compare.classify({"tableFound": True, "classes": {}}, True, [], "indoor")
        == "schedule_component_only"
    )


def test_cells_without_query_responses_do_not_pass_new_source():
    page = {"tableFound": True, "classes": {"": 8}}
    assert compare.classify(page, True, [], "indoor") == "schedule_component_only"
    queries = [
        {"path": "/x/getVenueCalendarList", "json": True},
        {"path": "/x/getVenueOrderList", "json": True},
    ]
    assert (
        compare.classify(page, True, queries, "indoor")
        == "query_samples_observed_not_bookability_acceptance"
    )


def test_visible_verification_or_wrong_source_never_passes():
    page = {"tableFound": True, "classes": {"": 8}, "visibleVerifications": ["NeVerify"]}
    assert compare.classify(page, True, [], "dashah_control") == "human_verification_required"
    assert compare.classify({"tableFound": True}, False, [], "indoor") == "unexpected_source"
