from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_host_core_public_edge_is_verified_before_delivery_activation() -> None:
    workflow = (ROOT / ".github/workflows/production-host-core.yml").read_text(
        encoding="utf-8"
    )

    prepare = workflow.index("remote prepare-cutover")
    public_edge = workflow.index("deploy_edge true false false")
    activation = workflow.index("remote cutover")
    final_health = workflow.index("remote health --include-public", activation)

    assert prepare < public_edge < activation < final_health
    assert "remote pause-host-delivery" in workflow
    assert "Real test notifications: none" in workflow
