from __future__ import annotations

from pathlib import Path
import tomllib

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
RETIRED_DEPENDABOT_WORKFLOWS = {
    "dependabot-triage.yml",
    "dependabot-reconcile.yml",
    "dependabot-ci-approval.yml",
    "nightly-dependabot-maintenance.yml",
}


def test_routine_dependabot_version_updates_are_disabled() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    updates = config["updates"]

    assert {
        ("pip", "/"),
        ("github-actions", "/"),
        ("npm", "/webapp"),
        ("docker", "/docker/airflow"),
        ("docker", "/docker/sender"),
    } == {(update["package-ecosystem"], update["directory"]) for update in updates}

    for update in updates:
        assert update["open-pull-requests-limit"] == 0
        assert update["schedule"]["interval"] == "monthly"
        assert "groups" not in update


def test_known_cryptography_security_baseline_is_patched() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]

    assert "cryptography==50.0.1" in project["dependencies"]
    assert "cryptography==48.0.1" not in project["dependencies"]


def test_legacy_dependabot_mutation_and_automerge_workflows_are_removed() -> None:
    for workflow_name in RETIRED_DEPENDABOT_WORKFLOWS:
        assert not (WORKFLOWS / workflow_name).exists()


def test_remaining_pr_reconciler_never_executes_pr_code_or_deploys() -> None:
    reconciler = (WORKFLOWS / "pr-reconciler.yml").read_text()

    assert "actions/checkout" not in reconciler
    assert "production-release" not in reconciler
    assert "production-ship" not in reconciler
    assert "environment: production" not in reconciler
    assert "workflow_call" not in reconciler
    assert "secrets." not in reconciler


def test_pr_reconciler_requires_a_complete_changed_file_listing() -> None:
    reconciler = (WORKFLOWS / "pr-reconciler.yml").read_text()

    assert "reported_changed_files" in reconciler
    assert "returned_changed_files" in reconciler
    assert "returned_changed_files != reported_changed_files" in reconciler
    assert "GitHub returned $returned_changed_files of $reported_changed_files" in reconciler
