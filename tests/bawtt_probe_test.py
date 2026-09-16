from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "bawtt_probe", Path(__file__).resolve().parents[1] / "scripts/probe_bawtt_ydmap.py"
)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
INDOOR = "bawtt_104036_indoor"
OUTDOOR = "bawtt_104036_outdoor"


def test_targets_are_isolated_and_exact() -> None:
    assert probe.booking_url(INDOOR).endswith("104036?salesItemId=111317")
    assert probe.booking_url(OUTDOOR).endswith("104036?salesItemId=103224")
    assert probe.source_matches(probe.booking_url(INDOOR), INDOOR)
    assert not probe.source_matches(probe.booking_url(OUTDOOR), INDOOR)
    with pytest.raises(ValueError, match="unsupported_target"):
        probe.booking_url("https://arbitrary.example")


@pytest.mark.parametrize(
    "url",
    [
        "http://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317",
        "https://bawtt.ydmap.cn.evil.example/booking/schedule/104036?salesItemId=111317",
        "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317&salesItemId=103224",
        "https://bawtt.ydmap.cn/booking/schedule/999999?salesItemId=111317",
        "https://bawtt.ydmap.cn/login",
    ],
)
def test_rejects_wrong_origin_product_or_path(url: str) -> None:
    assert not probe.source_matches(url, INDOOR)


def test_challenge_never_counts_as_ready() -> None:
    result = probe.summarize(
        INDOOR, probe.booking_url(INDOOR), {"challenge": True, "tableFound": True, "cells": 100}
    )
    assert result["reason"] == "access_verification_required"
    assert not result["structureReady"]
    assert not result["productionReady"]


@pytest.mark.parametrize("payload", [None, [], "not JSON", {}, {"tableFound": True, "cells": 0}])
def test_missing_or_empty_grid_is_not_success(payload: object) -> None:
    result = probe.summarize(INDOOR, probe.booking_url(INDOOR), payload)
    assert not result["structureReady"]


def test_visible_grid_does_not_authorize_notifications() -> None:
    result = probe.summarize(
        INDOOR,
        probe.booking_url(INDOOR),
        {
            "tableFound": True,
            "cells": 200,
            "cellsWithCourt": 200,
            "cellsWithExplicitClass": 0,
            "fieldNames": ["className", "expired", "className", "bad field", 1],
            "classCounts": {"locked": 4, "unknown_private_text": 3},
        },
    )
    assert result["structureReady"]
    assert not result["productionReady"]
    assert "availability" not in result
    assert result["classCounts"] == {"locked": 4}
    assert result["fieldNames"] == ["className", "expired"]


def test_redirect_cannot_relabel_another_venue() -> None:
    result = probe.summarize(INDOOR, probe.booking_url(OUTDOOR), {"tableFound": True, "cells": 100})
    assert not result["structureReady"]
    assert result["reason"] == "unexpected_redirect_or_source"


def test_main_probes_both_even_when_one_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = []

    def fake_probe(target: str) -> dict:
        seen.append(target)
        return {"target": target, "structureReady": target == OUTDOOR}

    monkeypatch.setattr(probe, "probe_target", fake_probe)
    assert probe.main() == 1
    assert seen == [INDOOR, OUTDOOR]
