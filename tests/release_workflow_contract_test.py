from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def test_only_one_workflow_listens_to_issue_comments():
    listeners = []
    for path in WORKFLOWS.glob("*.yml"):
        source = path.read_text(encoding="utf-8")
        if "issue_comment:" in source:
            listeners.append(path.name)

    assert listeners == ["ops-chatops.yml"]


def test_single_router_supports_mutually_exclusive_release_commands():
    workflow = (WORKFLOWS / "ops-chatops.yml").read_text(encoding="utf-8")

    assert 'command in {"preflight", "apply"}' in workflow
    assert 'command == "ship"' in workflow
    assert 'command == "tag"' in workflow
    assert "production-ship.yml" in workflow
    assert "release-tag-chatops.yml" in workflow
    assert "Publish one authoritative result" in workflow
    assert "Wait for main CI verify" not in workflow


def test_release_gate_fails_fast_when_ci_record_is_missing_and_plans_scope():
    workflow = (WORKFLOWS / "production-release.yml").read_text(encoding="utf-8")

    assert "--missing-check-wait-seconds 0" in workflow
    assert "scripts/release_plan.py" in workflow
    assert "deploy_webapp" in workflow
    assert "deploy_airflow" in workflow
    assert "deploy_sender" in workflow
    assert "planned=\\`$WEBAPP_PLANNED\\`" in workflow


def test_one_command_ship_applies_then_tags_exact_commit():
    workflow = (WORKFLOWS / "production-ship.yml").read_text(encoding="utf-8")

    assert "scripts/release_contract.py" in workflow
    assert "production-release.yml" in workflow
    assert "mode: apply" in workflow
    assert "release-tag-chatops.yml" in workflow
    assert workflow.index("production-release.yml") < workflow.index("release-tag-chatops.yml")


def test_airflow_apply_uses_transactional_health_and_restore_wrapper():
    workflow = (WORKFLOWS / "production-airflow.yml").read_text(encoding="utf-8")

    assert workflow.count("scripts/deploy_airflow_transaction.py") == 2
    apply_block = workflow.split("deploy_apply)", 1)[1].split("db_cleanup_check)", 1)[0]
    assert "scripts/deploy_airflow.py --apply" not in apply_block


def test_ci_is_component_aware_and_cancels_stale_pr_runs():
    workflow = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")

    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in workflow
    assert "Detect changed component surfaces" in workflow
    assert "scripts/release_plan.py" in workflow
    assert "steps.plan.outputs.ci_webapp" in workflow
    assert "steps.plan.outputs.ci_airflow" in workflow
    assert "steps.plan.outputs.ci_sender" in workflow
    assert "Validate active components and runtime drift" in workflow
    assert "scripts/check_active_components.py" in workflow


def test_named_release_tag_is_reusable_exact_immutable_and_resumable():
    workflow = (WORKFLOWS / "release-tag-chatops.yml").read_text(encoding="utf-8")

    assert "workflow_call:" in workflow
    assert "issue_comment:" not in workflow
    assert "scripts/release_contract.py" in workflow
    assert "scripts/github_release_gate.py" in workflow
    assert "--wait-seconds 0" in workflow
    assert 'git ls-remote origin "refs/tags/$VERSION^{}"' in workflow
    assert '"$remote_target" != "$TARGET_COMMIT"' in workflow
    assert 'git tag -a "$VERSION" "$TARGET_COMMIT"' in workflow
    assert 'gh release view "$VERSION"' in workflow
    assert 'gh release create "$VERSION"' in workflow
    assert "--verify-tag" in workflow
