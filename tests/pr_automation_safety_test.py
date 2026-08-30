from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def test_dependabot_groups_only_aggregate_approved_update_tiers() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())

    groups_by_ecosystem = {
        update["package-ecosystem"]: update.get("groups", {}) for update in config["updates"]
    }

    python_groups = groups_by_ecosystem["pip"]
    webapp_groups = groups_by_ecosystem["npm"]

    assert python_groups["python-patch"]["update-types"] == ["patch"]
    assert webapp_groups["webapp-patch"]["update-types"] == ["patch"]
    assert python_groups["python-dev-minor"]["update-types"] == ["minor"]
    assert webapp_groups["webapp-dev-minor"]["update-types"] == ["minor"]

    python_minor = set(python_groups["python-dev-minor"]["patterns"])
    webapp_minor = set(webapp_groups["webapp-dev-minor"]["patterns"])

    assert {"pytest", "pre-commit", "types-requests"} <= python_minor
    assert {"vite", "@vitejs/plugin-react", "@playwright/test"} <= webapp_minor

    # Runtime, deployment-control, and repository-wide rule-engine updates
    # remain individual PRs so the nightly maintainer validates each exact head.
    assert (
        not {
            "fastapi",
            "uvicorn",
            "selenium",
            "Appium-Python-Client",
            "ruff",
        }
        & python_minor
    )
    assert not {"wrangler", "@fontsource/roboto", "motion"} & webapp_minor


def test_dependabot_classifier_uses_verified_metadata_and_explicit_allowlists() -> None:
    triage = (WORKFLOWS / "dependabot-triage.yml").read_text()

    assert "npm_and_yarn:webapp-patch:/webapp" in triage
    assert "npm_and_yarn:webapp/package.json" in triage
    assert "npm_and_yarn:webapp/package-lock.json" in triage
    assert "DEPENDENCY_NAMES" in triage
    assert "python_minor_allowlist" in triage
    assert "webapp_minor_allowlist" in triage
    assert "version-update:semver-minor" in triage
    assert "dependabot-safe-update" in triage
    assert "automerge:dependency" in triage
    assert (
        "python_minor_allowlist='httpx|mypy|pre-commit|pytest|pytest-cov|types-paramiko|types-requests'"
        in triage
    )


def test_write_capable_pr_automation_never_executes_pr_code_or_deploys() -> None:
    workflow_names = [
        "dependabot-triage.yml",
        "dependabot-reconcile.yml",
        "nightly-dependabot-maintenance.yml",
        "pr-reconciler.yml",
    ]

    for workflow_name in workflow_names:
        text = (WORKFLOWS / workflow_name).read_text()

        assert "actions/checkout" not in text
        assert "production-release" not in text
        assert "production-ship" not in text
        assert "environment: production" not in text
        assert "workflow_call" not in text
        assert "secrets." not in text


def test_dependabot_merge_is_bound_to_the_classified_head_sha() -> None:
    triage = (WORKFLOWS / "dependabot-triage.yml").read_text()
    reconcile = (WORKFLOWS / "dependabot-reconcile.yml").read_text()

    assert 'context="dependabot-safe-update"' in triage
    assert 'select(.context == "dependabot-safe-update")' in reconcile
    assert "WORKFLOW_HEAD_SHA" in reconcile
    assert '"$WORKFLOW_HEAD_SHA" != "$head_sha"' in reconcile
    assert '-f expected_head_sha="$head_sha"' in reconcile
    assert '-f sha="$head_sha"' in reconcile
    assert '-f merge_method="squash"' in reconcile


def test_dependabot_merge_always_requires_exact_head_ci_success() -> None:
    reconcile = (WORKFLOWS / "dependabot-reconcile.yml").read_text()

    assert "actions/workflows/ci.yml/runs?head_sha=$head_sha&event=pull_request" in reconcile
    assert 'select(.head_sha == $sha and .status == "completed")' in reconcile
    assert 'if [[ "$ci_conclusion" != "success" ]]' in reconcile
    assert "Branch protection is intentionally not assumed" in reconcile
    assert "WORKFLOW_CONCLUSION" not in reconcile


def test_nightly_maintenance_runs_at_local_one_and_covers_every_dependabot_pr() -> None:
    nightly = (WORKFLOWS / "nightly-dependabot-maintenance.yml").read_text()

    assert 'cron: "0 8,9 * * *"' in nightly
    assert 'LOCAL_TZ="America/Los_Angeles"' in nightly
    assert '"$EVENT_NAME" == "schedule" && "$LOCAL_HOUR" != "01"' in nightly
    assert "actions/workflows/$WORKFLOW_FILE/runs?event=schedule" in nightly
    assert "pulls?state=open&base=main&per_page=100" in nightly
    assert '.user.login == "dependabot[bot]"' in nightly
    assert 'head_repo" != "$REPO"' in nightly


def test_nightly_maintenance_has_bounded_recovery_and_exact_head_merge() -> None:
    nightly = (WORKFLOWS / "nightly-dependabot-maintenance.yml").read_text()

    assert "reported_changed_files" in nightly
    assert "returned_changed_files" in nightly
    assert "dependency_paths_are_bounded" in nightly
    assert "control_plane_patches_are_bounded" in nightly
    assert "commits_are_dependabot_only" in nightly
    assert "pulls/$number/update-branch" in nightly
    assert "@dependabot recreate" in nightly
    assert 'gh run rerun "$ci_run_id" --failed' in nightly
    assert "actions/workflows/ci.yml/runs?head_sha=$sha&event=pull_request" in nightly
    assert '-f sha="$head_sha"' in nightly
    assert '-f merge_method="squash"' in nightly
    assert "maintenance:needs-repair" in nightly
    assert 'if [[ "$ci_conclusion" != "success" ]]' in nightly


def test_pr_reconciler_requires_a_complete_changed_file_listing() -> None:
    reconciler = (WORKFLOWS / "pr-reconciler.yml").read_text()

    assert "reported_changed_files" in reconciler
    assert "returned_changed_files" in reconciler
    assert "returned_changed_files != reported_changed_files" in reconciler
    assert "GitHub returned $returned_changed_files of $reported_changed_files" in reconciler


def test_dependabot_merge_response_has_valid_json_fallback() -> None:
    reconcile = (WORKFLOWS / "dependabot-reconcile.yml").read_text()

    assert "${merge_response:-{}}" not in reconcile
    assert "merge_response='{}'" in reconcile
    assert '<<< "$merge_response"' in reconcile
