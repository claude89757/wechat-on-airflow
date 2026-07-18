#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from _ops import (
    OpsError,
    emit,
    latest_successful_backup,
    merged_env,
    required_env,
    run,
)

DEFAULT_RETENTION_DAYS = 180


def default_cutoff(now: datetime, retention_days: int) -> datetime:
    if retention_days <= 0:
        raise OpsError("retention days must be positive")
    return (now.astimezone(UTC) - timedelta(days=retention_days)).replace(microsecond=0)


def confirmed_cutoff(value: str) -> datetime:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise OpsError("--confirm-delete-before must use YYYY-MM-DD") from exc
    return datetime.combine(parsed, time.min, tzinfo=UTC)


def cleanup_command(cutoff: datetime, apply: bool) -> list[str]:
    command = [
        "airflow",
        "db",
        "clean",
        "--clean-before-timestamp",
        cutoff.isoformat(),
    ]
    if apply:
        command.extend(["--skip-archive", "--error-on-cleanup-failure", "--yes"])
    else:
        command.append("--dry-run")
    return command


def parse_remote_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        if not line.startswith("{"):
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise OpsError("production cleanup command returned no structured result")


def remote_script() -> str:
    return r"""
set -eu
cd "$1"
expected_commit="$2"
cutoff="$3"
mode="$4"

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        return 127
    fi
}

service="$(compose ps --services --status running | awk '/^airflow-api-server$/{print; exit}')"
test -n "$service"
current_commit="$(git rev-parse HEAD)"
test "$current_commit" = "$expected_commit"

if [ "$mode" = "apply" ]; then
    compose exec -T "$service" airflow db clean \
        --clean-before-timestamp "$cutoff" \
        --skip-archive \
        --error-on-cleanup-failure \
        --yes </dev/null >/dev/null
else
    compose exec -T "$service" airflow db clean \
        --clean-before-timestamp "$cutoff" \
        --dry-run </dev/null >/dev/null
fi

python3 - "$current_commit" "$cutoff" "$mode" <<'PY'
import json
import sys

print(
    json.dumps(
        {
            "ok": True,
            "commit": sys.argv[1],
            "cutoff": sys.argv[2],
            "mode": sys.argv[3],
        },
        sort_keys=True,
    )
)
PY
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Airflow metadata cleanup outside the Task SDK boundary."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-delete-before")
    parser.add_argument("--retention-days", type=int, default=DEFAULT_RETENTION_DAYS)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path.home() / "airflow-production-backups",
    )
    args = parser.parse_args()

    if args.apply and not args.confirm_delete_before:
        raise OpsError("--apply requires --confirm-delete-before YYYY-MM-DD")
    if not args.apply and args.confirm_delete_before:
        raise OpsError("--confirm-delete-before is only valid with --apply")

    cutoff = (
        confirmed_cutoff(args.confirm_delete_before)
        if args.apply
        else default_cutoff(datetime.now(UTC), args.retention_days)
    )
    if args.apply and cutoff >= datetime.now(UTC):
        raise OpsError("confirmed deletion cutoff must be in the past")
    values = merged_env()
    remote = required_env(values, ["SERVER_IP", "PORT", "USERNAME", "PASSWORD", "REMOTE_PATH"])
    commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    status = run(["git", "status", "--porcelain"]).stdout.strip()
    upstream = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        check=False,
    )
    pushed = (
        upstream.returncode == 0
        and run(
            ["git", "merge-base", "--is-ancestor", commit, upstream.stdout.strip()], check=False
        ).returncode
        == 0
    )
    backup = latest_successful_backup(args.backup_dir)
    if args.apply and (status or not pushed or backup is None):
        raise OpsError(
            "apply requires a clean pushed commit and a verified encrypted database backup"
        )

    ssh_env = dict(values)
    ssh_env["SSHPASS"] = remote["PASSWORD"]
    command = [
        "sshpass",
        "-e",
        "ssh",
        "-o",
        "PreferredAuthentications=password",
        "-o",
        "PubkeyAuthentication=no",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=15",
        "-p",
        remote["PORT"],
        f"{remote['USERNAME']}@{remote['SERVER_IP']}",
        "bash",
        "-s",
        "--",
        remote["REMOTE_PATH"],
        commit,
        cutoff.isoformat(),
        "apply" if args.apply else "dry-run",
    ]
    result = run(command, env=ssh_env, check=False, input_text=remote_script())
    if result.returncode:
        raise OpsError(result.stderr.strip() or "production cleanup command failed")
    remote_result = parse_remote_result(result.stdout)
    payload = {
        "ok": remote_result.get("ok") is True,
        "mode": "apply" if args.apply else "dry-run",
        "cutoff": cutoff.isoformat(),
        "commit": commit,
        "remote_commit_matches": remote_result.get("commit") == commit,
        "backup_available": backup is not None,
        "records_deleted": args.apply,
    }
    payload["ok"] = (
        payload["ok"]
        and payload["remote_commit_matches"]
        and (not args.apply or payload["backup_available"])
    )
    emit(payload, args.format)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
