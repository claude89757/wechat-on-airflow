from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ydmap_date_query import blocked, snapshot  # noqa: E402


def test_real_verification_stops_even_with_loaded_cells():
    for key, value in [
        ("challenge", True),
        ("loginRequired", True),
        ("visibleVerifications", ["NeVerify"]),
    ]:
        assert blocked({key: value, "classes": {"": 20}})
    assert blocked({}, SimpleNamespace(results=[{"accessChallenge": True}]))
    assert not blocked({"visibleVerifications": [], "classes": {}}, SimpleNamespace(results=[]))


def test_snapshot_preserves_source_date_and_omits_private_data():
    page = {
        "url": "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317",
        "selectedDate": "2026-09-16",
        "selectedProduct": 111317,
        "tableFound": True,
        "classes": {},
        "courts": [],
        "token": "PRIVATE",
        "businessQueryMethods": ["PRIVATE"],
    }
    driver = SimpleNamespace(execute_script=lambda _: page)
    result = snapshot(driver, "indoor")
    assert result["sourceMatches"]
    assert result["selectedProduct"] == 111317
    assert result["selectedDate"] == "2026-09-16"
    assert "PRIVATE" not in str(result)
    assert not snapshot(driver, "outdoor")["sourceMatches"]


def test_probe_does_not_use_prod_browser_or_slot_actions():
    source = (Path(__file__).parents[1] / "scripts/ydmap_date_query.py").read_text()
    for forbidden in (
        "/tmp/dsh_ydmap_profile",
        "get_cookies",
        "setCookie",
        "createOrder",
        "pkill",
        "--user-agent",
        "Object.defineProperty",
        "AutomationControlled",
    ):
        assert forbidden not in source
    assert "port == 9224" in source
    assert "visible[0].click()" in source
    assert 'not report["dateClicks"]' in source
