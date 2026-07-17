#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _ops import OpsError, docker_compose_command, emit, latest_successful_backup, run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate rollback inputs without changing production."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path.home() / "airflow-production-backups",
    )
    args = parser.parse_args()

    head = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    previous = run(["git", "rev-parse", "HEAD^"], check=False)
    backup = latest_successful_backup(args.backup_dir)
    compose_command = docker_compose_command()
    compose = run(
        [
            *compose_command,
            "--env-file",
            ".env.example",
            "config",
            "--quiet",
        ],
        check=False,
    )
    sender_compose = run(
        [
            *compose_command,
            "--env-file",
            ".env.example",
            "-f",
            "docker-compose.sender.yml",
            "config",
            "--quiet",
        ],
        check=False,
    )
    checks = {
        "previous_commit_exists": previous.returncode == 0,
        "encrypted_database_backup": backup is not None,
        "compose_valid": compose.returncode == 0,
        "sender_compose_valid": sender_compose.returncode == 0,
        "restore_runbook_exists": Path("docs/runbooks/rollback.md").is_file(),
    }
    payload = {
        "ok": all(checks.values()),
        "dry_run": args.dry_run,
        "current_commit": head,
        "previous_commit": previous.stdout.strip() if previous.returncode == 0 else None,
        "backup_file": str(backup) if backup else None,
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
