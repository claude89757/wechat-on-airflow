#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _ops import OpsError, docker_compose_command, emit, latest_successful_backup, run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate reversible production deploy prerequisites."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path.home() / "airflow-production-backups",
    )
    args = parser.parse_args()

    status = run(["git", "status", "--porcelain"]).stdout.strip()
    commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    branch = run(["git", "branch", "--show-current"]).stdout.strip()
    upstream_result = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        check=False,
    )
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else ""
    pushed = False
    if upstream:
        pushed = (
            run(["git", "merge-base", "--is-ancestor", commit, upstream], check=False).returncode
            == 0
        )

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
    backup = latest_successful_backup(args.backup_dir)
    checks = {
        "clean_worktree": not status,
        "has_upstream": bool(upstream),
        "commit_is_pushed": pushed,
        "compose_valid": compose.returncode == 0,
        "sender_compose_valid": sender_compose.returncode == 0,
        "encrypted_database_backup": backup is not None,
    }
    payload = {
        "ok": all(checks.values()),
        "dry_run": args.dry_run,
        "commit": commit,
        "branch": branch,
        "upstream": upstream,
        "checks": checks,
        "backup_file": str(backup) if backup else None,
    }
    emit(payload, args.format)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"deploy-check: {exc}")
        raise SystemExit(1) from exc
