from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import deploy_airflow_transaction  # noqa: E402


def completed(
    returncode: int,
    payload: dict[str, object] | None = None,
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    stdout = f"{json.dumps(payload)}\n" if payload is not None else ""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def deployment_payload(previous_commit: str) -> dict[str, object]:
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


def test_failed_full_health_never_rolls_back_to_legacy_runtime():
    target = "a" * 40
    previous = "b" * 40
    results = iter(
        [
            completed(0, deployment_payload(previous)),
            completed(1, {"ok": False}, "target unhealthy"),
        ]
    )
    commands = []

    def runner(command, *, check):
        assert check is False
        commands.append(command)
        return next(results)

    payload, code = deploy_airflow_transaction.deploy_with_health(target, runner=runner)
    assert code == 1 and payload["ok"] is False
    assert payload["automatic_restore"]["attempted"] is False
    assert len(commands) == 2
    assert "pauses_host_delivery" in payload["recovery_policy"]


def test_failed_install_is_not_reported_as_healthy():
    import pytest

    with pytest.raises(deploy_airflow_transaction.OpsError):
        deploy_airflow_transaction.deploy_with_health(
            "a" * 40, runner=lambda command, *, check: completed(1, None, "failure")
        )
