from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_dependabot_groups_only_aggregate_patch_updates() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())

    groups_by_ecosystem = {
        update["package-ecosystem"]: update.get("groups", {})
        for update in config["updates"]
    }

    assert groups_by_ecosystem["pip"]["python-patch"]["update-types"] == ["patch"]
    assert groups_by_ecosystem["npm"]["webapp-patch"]["update-types"] == ["patch"]


def test_write_capable_pr_automation_never_executes_pr_code_or_deploys() -> None:
    workflow_names = [
        "dependabot-triage.yml",
        "dependabot-reconcile.yml",
        "pr-reconciler.yml",
    ]

    for workflow_name in workflow_names:
        text = (WORKFLOWS / workflow_name).read_text()

        assert "actions/checkout" not in text
        assert "production-release" not in text
        assert "production-ship" not in text
        assert "environment: production" not in text
        assert "workflow_call" not in text


def test_dependabot_merge_is_bound_to_the_classified_head_sha() -> None:
    triage = (WORKFLOWS / "dependabot-triage.yml").read_text()
    reconcile = (WORKFLOWS / "dependabot-reconcile.yml").read_text()

    assert 'context="dependabot-safe-patch"' in triage
    assert 'select(.context == "dependabot-safe-patch")' in reconcile
    assert '-f expected_head_sha="$head_sha"' in reconcile
    assert '-f sha="$head_sha"' in reconcile
    assert '-f merge_method="squash"' in reconcile
