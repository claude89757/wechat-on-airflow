#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

from _ops import REPO_ROOT, OpsError, docker_compose_command, emit, run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate rollback inputs without changing production."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    previous = run(["git", "rev-parse", "HEAD^"], check=False)
    compose_command = docker_compose_command()
    compose = run(
        [
            *compose_command,
            "config",
            "--quiet",
        ],
        env={**os.environ, "AIRFLOW_SECRET_DIR": str(REPO_ROOT / ".local" / "secrets")},
        check=False,
    )
    sender_compose = run(
        [
            *compose_command,
            "-f",
            "docker-compose.sender.yml",
            "config",
            "--quiet",
        ],
        check=False,
    )
    checks = {
        "previous_commit_exists": previous.returncode == 0,
        "compose_valid": compose.returncode == 0,
        "sender_compose_valid": sender_compose.returncode == 0,
        "restore_runbook_exists": Path("docs/runbooks/rollback.md").is_file(),
    }
    payload = {
        "ok": all(checks.values()),
        "dry_run": args.dry_run,
        "current_commit": head,
        "previous_commit": previous.stdout.strip() if previous.returncode == 0 else None,
        "checks": checks,
    }
    emit(payload, args.format)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"rollback-check: {exc}")
        raise SystemExit(1) from exc
