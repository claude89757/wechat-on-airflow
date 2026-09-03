from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_v070_waits_for_three_natural_cycles_and_checks_business_flow() -> None:
    workflow = (ROOT / ".github/workflows/production-host-core-v070.yml").read_text(
        encoding="utf-8"
    )

    assert "Observe three natural one-minute cycles and verify business flow" in workflow
    assert "sleep 180" in workflow
    assert "shadow-evidence --target-commit" in workflow
    assert "needs: [resolve, deploy]" in workflow
    assert "needs: [resolve, natural_cycles]" in workflow
    assert "operation: health" in workflow


def test_business_acceptance_precedes_immutable_version_release() -> None:
    workflow = (ROOT / ".github/workflows/production-host-core-v070.yml").read_text(
        encoding="utf-8"
    )

    assert "uses: ./.github/workflows/production-release.yml" in workflow
    assert "uses: ./.github/workflows/release-tag-chatops.yml" in workflow
    assert workflow.index("  contract:") < workflow.index("  cutover:")
    assert workflow.index("  cutover:") < workflow.index("  deploy:")
    assert workflow.index("  deploy:") < workflow.index("  natural_cycles:")
    assert workflow.index("  natural_cycles:") < workflow.index("  acceptance:")
    assert workflow.index("  acceptance:") < workflow.index("  tag:")


def test_v070_runs_after_the_d1_reset_and_skips_an_existing_release() -> None:
    workflow = (ROOT / ".github/workflows/production-host-core-v070.yml").read_text(
        encoding="utf-8"
    )

    assert 'cron: "5 0 4 9 *"' in workflow
    assert 'cron: "25 0 4 9 *"' in workflow
    assert "push:" not in workflow.split("permissions:", 1)[0]
    assert "refs/tags/0.7.0" in workflow
    assert "should_run=false" in workflow
    assert 'target_commit="$(git rev-parse origin/main)"' in workflow


def test_owner_only_comment_can_trigger_the_same_release_transaction() -> None:
    workflow = (ROOT / ".github/workflows/production-host-core-v070.yml").read_text(
        encoding="utf-8"
    )

    assert "issue_comment:" in workflow
    assert "github.event.issue.number == 39" in workflow
    assert "github.event.comment.user.login == github.repository_owner" in workflow
    assert "github.event.comment.body == '/ops host-core-v070'" in workflow
