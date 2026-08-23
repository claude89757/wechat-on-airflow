#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

from _ops import OpsError, emit, run

SCRIPTS_DIR = Path(__file__).resolve().parent
Runner = Callable[..., CompletedProcess[str]]


def parse_payload(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def command_summary(result: CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "payload": parse_payload(result.stdout or ""),
        "stderr_tail": (result.stderr or "").strip().splitlines()[-1:] or [],
    }


def relay(result: CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )


def deploy_command(target_commit: str, recover_active_tasks: bool = False) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "deploy_airflow.py"),
        "--apply",
        "--target-commit",
        target_commit,
        "--format",
        "json",
    ]
    if recover_active_tasks:
        command.insert(3, "--recover-active-tasks")
    return command


def health_command(expected_commit: str) -> list[str]:
    return [
        sys.executable,
        str(SCRIPTS_DIR / "production_health.py"),
        "--expected-commit",
        expected_commit,
        "--format",
        "json",
    ]


def deploy_with_health(
    target_commit: str,
    *,
    recover_active_tasks: bool = False,
    runner: Runner = run,
) -> tuple[dict[str, Any], int]:
    deployment = runner(
        deploy_command(target_commit, recover_active_tasks),
        check=False,
    )
    relay(deployment)
    if deployment.returncode != 0:
        raise OpsError("Airflow deployment failed before the full health gate")

    deployment_payload = parse_payload(deployment.stdout or "")
    remote_payload = deployment_payload.get("remote")
    previous_commit = (
        remote_payload.get("previous_commit") if isinstance(remote_payload, dict) else None
    )
    if not isinstance(previous_commit, str) or len(previous_commit) != 40:
        raise OpsError("Airflow deployment did not return a rollback commit")

    health = runner(health_command(target_commit), check=False)
    relay(health)
    if health.returncode == 0:
        return (
            {
                "ok": True,
                "target_commit": target_commit,
                "previous_commit": previous_commit,
                "deployment": command_summary(deployment),
                "health": command_summary(health),
                "automatic_restore": {"attempted": False, "ok": None},
            },
            0,
        )

    restore = runner(deploy_command(previous_commit), check=False)
    relay(restore)
    restore_health: CompletedProcess[str] | None = None
    if restore.returncode == 0:
        restore_health = runner(health_command(previous_commit), check=False)
        relay(restore_health)

    restore_ok = bool(
        restore.returncode == 0
        and restore_health is not None
        and restore_health.returncode == 0
    )
    return (
        {
            "ok": False,
            "target_commit": target_commit,
            "previous_commit": previous_commit,
            "deployment": command_summary(deployment),
            "health": command_summary(health),
            "automatic_restore": {
                "attempted": True,
                "target_commit": previous_commit,
                "deploy": command_summary(restore),
                "health": command_summary(restore_health) if restore_health else None,
                "ok": restore_ok,
            },
        },
        1,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy Airflow, require full health, and automatically restore on failure."
    )
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--recover-active-tasks", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    payload, exit_code = deploy_with_health(
        args.target_commit,
        recover_active_tasks=args.recover_active_tasks,
    )
    emit(payload, args.format)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"deploy-airflow-transaction: {exc}")
        raise SystemExit(1) from exc
