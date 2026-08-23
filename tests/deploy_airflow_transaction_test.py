from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import deploy_airflow_transaction  # noqa: E402


def completed(returncode: int, payload: dict | None = None, stderr: str = ""):
    stdout = f"{json.dumps(payload)}
" if payload is not None else ""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def deployment_payload(previous_commit: str) -> dict:
    return {
        "ok": True,
        "remote": {
            "ok": True,
            "applied": True,
            "previous_commit": previous_commit,
        },
    }


def test_successful_health_does_not_restore():
    target = "a" * 40
    previous = "b" * 40
    results = iter([completed(0, deployment_payload(previous)), completed(0, {"ok": True})])
    commands: list[list[str]] = []

    def runner(command, *, check):
        assert check is False
        commands.append(command)
        return next(results)

    payload, exit_code = deploy_airflow_transaction.deploy_with_health(target, runner=runner)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["automatic_restore"] == {"attempted": False, "ok": None}
    assert len(commands) == 2


def test_failed_full_health_restores_previous_commit_and_still_fails_release():
    target = "a" * 40
    previous = "b" * 40
    results = iter(
        [
            completed(0, deployment_payload(previous)),
            completed(1, {"ok": False}, "target unhealthy"),
            completed(0, deployment_payload(target)),
            completed(0, {"ok": True}),
        ]
    )
    commands: list[list[str]] = []

    def runner(command, *, check):
        assert check is False
        commands.append(command)
        return next(results)

    payload, exit_code = deploy_airflow_transaction.deploy_with_health(target, runner=runner)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["automatic_restore"]["attempted"] is True
    assert payload["automatic_restore"]["target_commit"] == previous
    assert payload["automatic_restore"]["ok"] is True
    assert previous in commands[2]
    assert previous in commands[3]


def test_failed_restore_is_reported_without_false_success():
    target = "a" * 40
    previous = "b" * 40
    results = iter(
        [
            completed(0, deployment_payload(previous)),
            completed(1, {"ok": False}),
            completed(1, None, "restore failed"),
        ]
    )

    payload, exit_code = deploy_airflow_transaction.deploy_with_health(
        target,
        runner=lambda command, *, check: next(results),
    )

    assert exit_code == 1
    assert payload["automatic_restore"]["attempted"] is True
    assert payload["automatic_restore"]["ok"] is False
    assert payload["automatic_restore"]["health"] is None
