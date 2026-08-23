from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_gate_fails_fast_when_ci_record_is_missing():
    workflow = (ROOT / ".github/workflows/production-release.yml").read_text(encoding="utf-8")

    assert "--missing-check-wait-seconds 0" in workflow


def test_airflow_apply_uses_transactional_health_and_restore_wrapper():
    workflow = (ROOT / ".github/workflows/production-airflow.yml").read_text(encoding="utf-8")

    assert workflow.count("scripts/deploy_airflow_transaction.py") == 2
    apply_block = workflow.split("deploy_apply)", 1)[1].split("db_cleanup_check)", 1)[0]
    assert "scripts/deploy_airflow.py --apply" not in apply_block


def test_runtime_drift_gate_is_explicit_in_ci():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Validate active components and runtime drift" in workflow
    assert "scripts/check_active_components.py" in workflow


def test_named_release_tag_is_owner_only_exact_immutable_and_resumable():
    workflow = (ROOT / ".github/workflows/release-tag-chatops.yml").read_text(encoding="utf-8")

    assert "github.event.issue.number == 39" in workflow
    assert "github.event.comment.user.login == github.repository_owner" in workflow
    assert "([0-9]+\\.[0-9]+\\.[0-9]+)" in workflow
    assert "([0-9a-f]{40})" in workflow
    assert "scripts/github_release_gate.py" in workflow
    assert "--wait-seconds 0" in workflow
    assert 'git ls-remote origin "refs/tags/$VERSION^{}"' in workflow
    assert '"$remote_target" != "$TARGET_COMMIT"' in workflow
    assert 'git tag -a "$VERSION" "$TARGET_COMMIT"' in workflow
    assert 'gh release view "$VERSION"' in workflow
    assert 'gh release create "$VERSION"' in workflow
    assert "--verify-tag" in workflow
