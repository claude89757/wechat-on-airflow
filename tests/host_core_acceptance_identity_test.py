from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("operation", ["acceptance", "health", "pause"])
@pytest.mark.parametrize("state", ["same_release", "source_drift", "runtime_drift", "dirty"])
def test_observation_and_pause_never_checkout_or_operate_on_another_release(
    tmp_path, operation, state
):
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-host-core.yml").read_text())
    step = next(
        step for step in workflow["jobs"]["operate"]["steps"] if step.get("id") == "prepare_remote"
    )
    remote = step["run"].split("<<'REMOTE'\n", 1)[1].split("\nREMOTE\n", 1)[0]
    target = "a" * 40
    calls = tmp_path / "calls"
    setup = """
git() {
    printf 'git %s\\n' "$*" >> "$CALLS"
    case "$*" in
        'rev-parse HEAD') printf '%s\\n' "$SOURCE_SHA" ;;
        'status --porcelain --untracked-files=no') printf '%s' "$DIRTY" ;;
        *) echo 'Unexpected mutating git call' >&2; return 99 ;;
    esac
}
docker() {
    printf 'docker %s\\n' "$*" >> "$CALLS"
    case "$*" in
        'compose exec -T zacks-api python -c '*) printf '%s\\n' "$LIVE_SHA" ;;
        *) echo 'Unexpected container mutation' >&2; return 99 ;;
    esac
}
"""
    result = subprocess.run(
        ["bash", "-c", setup + remote, "identity-check", str(tmp_path), target, operation],
        env={
            **os.environ,
            "CALLS": str(calls),
            "SOURCE_SHA": "b" * 40 if state == "source_drift" else target,
            "LIVE_SHA": "b" * 40 if state == "runtime_drift" else target,
            "DIRTY": " M tracked-file" if state == "dirty" else "",
        },
        text=True,
        capture_output=True,
        check=False,
    )
    assert "git fetch" not in calls.read_text()
    assert "git checkout" not in calls.read_text()
    if state == "same_release":
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"{target} {target}"
    else:
        assert result.returncode != 0
        assert result.stdout == ""
    if state in {"source_drift", "dirty"}:
        assert "docker " not in calls.read_text()
