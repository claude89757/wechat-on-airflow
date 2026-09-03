from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v070_waits_for_three_natural_cycles_and_checks_business_flow() -> None:
    workflow = (
        ROOT / ".github/workflows/production-host-core-v070.yml"
    ).read_text(encoding="utf-8")

    assert "Observe three natural one-minute cycles and verify business flow" in workflow
    assert "sleep 180" in workflow
    assert "shadow-evidence --target-commit" in workflow
    assert "needs: natural_cycles" in workflow
    assert "operation: health" in workflow


def test_business_acceptance_runs_after_version_ship() -> None:
    workflow = (
        ROOT / ".github/workflows/production-host-core-v070.yml"
    ).read_text(encoding="utf-8")

    assert workflow.index("  ship:") < workflow.index("  natural_cycles:")
    assert workflow.index("  natural_cycles:") < workflow.index("  acceptance:")
