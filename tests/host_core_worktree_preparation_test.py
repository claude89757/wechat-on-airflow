from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_host_core_backs_up_bounded_tracked_drift_before_checkout() -> None:
    workflow = (ROOT / ".github/workflows/production-host-core.yml").read_text(encoding="utf-8")
    prepare = workflow.split("      - name: Back up and clear bounded tracked worktree drift", 1)[
        1
    ].split("      - name: Operate host core", 1)[0]

    assert "scripts/repair_airflow_worktree.py" in prepare
    assert "--expected-dirty-count 1" in prepare
    assert "--if-needed" in prepare
    assert prepare.index("repair_airflow_worktree.py") < prepare.index("git checkout --detach")


def test_host_core_preserves_untracked_runtime_files() -> None:
    workflow = (ROOT / ".github/workflows/production-host-core.yml").read_text(encoding="utf-8")
    prepare = workflow.split("      - name: Prepare exact remote commit", 1)[1].split(
        "      - name: Operate host core", 1
    )[0]

    assert "git status --porcelain --untracked-files=no" in prepare
    assert 'git status --porcelain)\\"' not in prepare
