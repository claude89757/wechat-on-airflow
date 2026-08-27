#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from _ops import OpsError, airflow_remote, emit, run, ssh_command

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def resolve_target_commit(revision: str) -> str:
    result = run(["git", "rev-parse", "--verify", f"{revision}^{{commit}}"])
    commit = result.stdout.strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise OpsError("target revision did not resolve to a full commit")
    return commit


def require_main_commit(target_commit: str) -> None:
    run(["git", "fetch", "--quiet", "origin", "main"])
    if (
        run(
            ["git", "merge-base", "--is-ancestor", target_commit, "origin/main"],
            check=False,
        ).returncode
        != 0
    ):
        raise OpsError("target commit is not on origin/main")


def parse_remote_result(output: str) -> dict[str, Any]:
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
    raise OpsError("Airflow worktree repair did not return a structured result")


def remote_script() -> str:
    return r"""\
set -eu
repo_path="$1"
operation_commit="$2"
expected_dirty_count="$3"
allow_clean="$4"
cd "$repo_path"

current_commit="$(git rev-parse HEAD)"
tracked_status="$(git status --porcelain --untracked-files=no)"
tracked_dirty_count="$(printf '%s\n' "$tracked_status" | awk 'NF {count += 1} END {print count + 0}')"

if [ "$tracked_dirty_count" -eq 0 ] && [ "$allow_clean" = "true" ]; then
    CURRENT_COMMIT="$current_commit" OPERATION_COMMIT="$operation_commit" python3 - <<'PY'
import json
import os

print(
    json.dumps(
        {
            "ok": True,
            "applied": False,
            "already_clean": True,
            "backup_created": False,
            "backup_restore_check": None,
            "current_commit": os.environ["CURRENT_COMMIT"],
            "operation_commit": os.environ["OPERATION_COMMIT"],
            "tracked_dirty_count_before": 0,
            "tracked_dirty_count_after": 0,
            "untracked_files_preserved": True,
            "services_restarted": False,
            "database_unchanged": True,
        },
        sort_keys=True,
    )
)
PY
    exit 0
fi

if [ "$tracked_dirty_count" -ne "$expected_dirty_count" ]; then
    printf 'tracked dirty count changed before repair\n' >&2
    exit 1
fi

umask 077
git_dir="$(git rev-parse --git-dir)"
backup_dir="$git_dir/ops-backups"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
nonce="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(8))
PY
)"
backup_id="tracked-drift-${timestamp}-${nonce}"
patch_file="$backup_dir/${backup_id}.patch"
metadata_file="$backup_dir/${backup_id}.json"

git diff --binary --full-index --no-ext-diff HEAD -- >"$patch_file"
test -s "$patch_file"
chmod 600 "$patch_file"

patch_sha256="$(python3 - "$patch_file" <<'PY'
import hashlib
import sys

with open(sys.argv[1], "rb") as handle:
    print(hashlib.sha256(handle.read()).hexdigest())
PY
)"
patch_bytes="$(wc -c <"$patch_file" | tr -d ' ')"
test "$patch_bytes" -gt 0

git reset --hard HEAD >/dev/null
tracked_status_after="$(git status --porcelain --untracked-files=no)"
tracked_dirty_count_after="$(
    printf '%s\n' "$tracked_status_after" | awk 'NF {count += 1} END {print count + 0}'
)"
test "$tracked_dirty_count_after" -eq 0
git apply --check --binary "$patch_file"

BACKUP_ID="$backup_id" \
CURRENT_COMMIT="$current_commit" \
OPERATION_COMMIT="$operation_commit" \
PATCH_SHA256="$patch_sha256" \
PATCH_BYTES="$patch_bytes" \
DIRTY_COUNT="$tracked_dirty_count" \
METADATA_FILE="$metadata_file" \
python3 - <<'PY'
import json
import os
from datetime import UTC, datetime

metadata = {
    "backup_id": os.environ["BACKUP_ID"],
    "created_at": datetime.now(UTC).isoformat(),
    "current_commit": os.environ["CURRENT_COMMIT"],
    "operation_commit": os.environ["OPERATION_COMMIT"],
    "patch_sha256": os.environ["PATCH_SHA256"],
    "patch_bytes": int(os.environ["PATCH_BYTES"]),
    "tracked_dirty_count": int(os.environ["DIRTY_COUNT"]),
}
with open(os.environ["METADATA_FILE"], "w", encoding="utf-8") as handle:
    json.dump(metadata, handle, sort_keys=True)
    handle.write("\n")
PY
chmod 600 "$metadata_file"

BACKUP_ID="$backup_id" \
CURRENT_COMMIT="$current_commit" \
OPERATION_COMMIT="$operation_commit" \
PATCH_SHA256="$patch_sha256" \
PATCH_BYTES="$patch_bytes" \
DIRTY_COUNT_BEFORE="$tracked_dirty_count" \
DIRTY_COUNT_AFTER="$tracked_dirty_count_after" \
python3 - <<'PY'
import json
import os

print(
    json.dumps(
        {
            "ok": True,
            "applied": True,
            "already_clean": False,
            "backup_created": True,
            "backup_id": os.environ["BACKUP_ID"],
            "backup_patch_sha256": os.environ["PATCH_SHA256"],
            "backup_patch_bytes": int(os.environ["PATCH_BYTES"]),
            "backup_restore_check": True,
            "current_commit": os.environ["CURRENT_COMMIT"],
            "operation_commit": os.environ["OPERATION_COMMIT"],
            "tracked_dirty_count_before": int(os.environ["DIRTY_COUNT_BEFORE"]),
            "tracked_dirty_count_after": int(os.environ["DIRTY_COUNT_AFTER"]),
            "untracked_files_preserved": True,
            "services_restarted": False,
            "database_unchanged": True,
        },
        sort_keys=True,
    )
)
PY
"""


def repair_succeeded(payload: dict[str, Any], expected_dirty_count: int) -> bool:
    common = (
        payload.get("ok") is True
        and payload.get("tracked_dirty_count_after") == 0
        and payload.get("services_restarted") is False
        and payload.get("database_unchanged") is True
        and payload.get("untracked_files_preserved") is True
    )
    if not common:
        return False
    if payload.get("already_clean") is True:
        return (
            payload.get("applied") is False
            and payload.get("backup_created") is False
            and payload.get("tracked_dirty_count_before") == 0
        )
    return (
        payload.get("applied") is True
        and payload.get("backup_created") is True
        and payload.get("backup_restore_check") is True
        and payload.get("tracked_dirty_count_before") == expected_dirty_count
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up and clear a bounded tracked-file drift in the Airflow checkout."
    )
    parser.add_argument("--target-commit", default="HEAD")
    parser.add_argument("--expected-dirty-count", type=int, default=1)
    parser.add_argument("--if-needed", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    if args.expected_dirty_count != 1:
        raise OpsError("the protected repair requires exactly one tracked dirty entry")

    target_commit = resolve_target_commit(args.target_commit)
    require_main_commit(target_commit)
    remote = airflow_remote()
    result = run(
        [
            *ssh_command(remote),
            "bash",
            "-s",
            "--",
            remote["repository_path"],
            target_commit,
            str(args.expected_dirty_count),
            "true" if args.if_needed else "false",
        ],
        check=False,
        input_text=remote_script(),
    )
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise OpsError(detail[-1] if detail else "Airflow worktree repair failed")

    payload = parse_remote_result(result.stdout)
    if not repair_succeeded(payload, args.expected_dirty_count):
        raise OpsError("Airflow worktree repair verification failed")
    emit(payload, args.format)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"repair-airflow-worktree: {exc}")
        raise SystemExit(1) from exc
