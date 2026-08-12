#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, emit, run, sender_remote, ssh_command

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def resolve_target_commit(revision: str) -> str:
    result = run(["git", "rev-parse", "--verify", f"{revision}^{{commit}}"])
    commit = result.stdout.strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise OpsError("target revision did not resolve to a full commit")
    run(["git", "fetch", "--quiet", "origin", "main"])
    if (
        run(
            ["git", "merge-base", "--is-ancestor", commit, "origin/main"],
            check=False,
        ).returncode
        != 0
    ):
        raise OpsError("target commit is not on origin/main")
    return commit


def parse_remote_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise OpsError("sender operation returned no structured result")


def remote_script() -> str:
    return r"""
set -eu
target_commit="$1"
mode="$2"
install_dir="$3"
credential_dir="$4"
legacy_file="/etc/wechat-sender.env"
service_file="/etc/systemd/system/wechat-sender.service"
venv_dir="/opt/wechat-sender-venv"

current_commit=""
if [ -d "$install_dir/.git" ]; then
    current_commit="$(git -C "$install_dir" rev-parse HEAD)"
fi

health() {
    service_enabled="$(systemctl is-enabled wechat-sender.service 2>/dev/null || true)"
    service_active="$(systemctl is-active wechat-sender.service 2>/dev/null || true)"
    ready=false
    if curl --fail --silent --show-error --max-time 5 http://127.0.0.1:7001/readyz >/dev/null; then
        ready=true
    fi
    python3 - "$current_commit" "$service_enabled" "$service_active" "$ready" \
        "$credential_dir" "$legacy_file" <<'PY'
import json
import stat
import sys
from pathlib import Path

directory = Path(sys.argv[5])
legacy_file = Path(sys.argv[6])
expected_files = ("wechat_allowed_device_name", "wechat_appium_url")
try:
    directory_stat = directory.stat()
    directory_ready = (
        directory.is_dir()
        and stat.S_IMODE(directory_stat.st_mode) == 0o700
        and directory_stat.st_uid == 0
    )
except OSError:
    directory_ready = False
files = {}
for name in expected_files:
    path = directory / name
    try:
        details = path.stat()
        files[name] = {
            "present": path.is_file(),
            "nonempty": path.is_file() and details.st_size > 0,
            "mode": stat.S_IMODE(details.st_mode),
            "owned_by_root": details.st_uid == 0,
        }
    except OSError:
        files[name] = {
            "present": False,
            "nonempty": False,
            "mode": None,
            "owned_by_root": False,
        }
files_ready = all(
    details["present"]
    and details["nonempty"]
    and details["mode"] == 0o600
    and details["owned_by_root"]
    for details in files.values()
)
credentials_ready = directory_ready and files_ready
legacy_file_absent = not legacy_file.exists()

print(json.dumps({
    "ok": (
        sys.argv[2] == "enabled"
        and sys.argv[3] == "active"
        and sys.argv[4] == "true"
        and credentials_ready
        and legacy_file_absent
    ),
    "commit": sys.argv[1] or None,
    "service_enabled": sys.argv[2] == "enabled",
    "service_active": sys.argv[3] == "active",
    "ready": sys.argv[4] == "true",
    "credentials": {
        "ready": credentials_ready,
        "directory_ready": directory_ready,
        "files": files,
        "legacy_file_absent": legacy_file_absent,
    },
}, sort_keys=True))
PY
}

if [ "$mode" = "health" ]; then
    health
    exit 0
fi

credentials_ready=false
if [ -s "$credential_dir/wechat_allowed_device_name" ] && \
   [ -s "$credential_dir/wechat_appium_url" ]; then
    credentials_ready=true
fi
legacy_ready=false
if [ -s "$legacy_file" ]; then
    legacy_ready=true
fi

if [ "$mode" = "dry-run" ]; then
    test "$credentials_ready" = true || test "$legacy_ready" = true
    git -C "$install_dir" fetch --quiet origin
    git -C "$install_dir" cat-file -e "$target_commit^{commit}"
    python3 - "$current_commit" "$target_commit" "$credentials_ready" "$legacy_ready" <<'PY'
import json
import sys

print(json.dumps({
    "ok": True,
    "applied": False,
    "current_commit": sys.argv[1] or None,
    "target_commit": sys.argv[2],
    "credentials_ready": sys.argv[3] == "true",
    "legacy_migration_required": sys.argv[3] != "true" and sys.argv[4] == "true",
}, sort_keys=True))
PY
    exit 0
fi

test "$mode" = "apply"
test "$(id -u)" = 0

python3 - "$legacy_file" "$credential_dir" <<'PY'
import os
import sys
from pathlib import Path

legacy = Path(sys.argv[1])
directory = Path(sys.argv[2])
mapping = {
    "WECHAT_ALLOWED_DEVICE_NAME": "wechat_allowed_device_name",
    "WECHAT_APPIUM_URL": "wechat_appium_url",
}
values = {}
if legacy.is_file():
    for raw_line in legacy.read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line or raw_line.lstrip().startswith("#"):
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
directory.mkdir(mode=0o700, parents=True, exist_ok=True)
directory.chmod(0o700)
for legacy_name, filename in mapping.items():
    destination = directory / filename
    if destination.is_file() and destination.stat().st_size:
        destination.chmod(0o600)
        continue
    value = values.get(legacy_name, "")
    if not value:
        raise SystemExit(f"missing sender credential: {legacy_name}")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value + "\n")
PY

unit_backup="$(mktemp)"
if [ -f "$service_file" ]; then
    cp -p "$service_file" "$unit_backup"
else
    : >"$unit_backup"
fi

rollback() {
    rc="${1:-$?}"
    trap - EXIT HUP INT TERM
    if [ "$rc" -ne 0 ]; then
        if [ -n "$current_commit" ]; then
            git -C "$install_dir" checkout --quiet --detach "$current_commit" || true
        fi
        if [ -s "$unit_backup" ]; then
            cp -p "$unit_backup" "$service_file" || true
        fi
        if [ -d "${venv_dir}.previous" ]; then
            rm -rf "${venv_dir}.failed" || true
            if [ -d "$venv_dir" ]; then
                mv "$venv_dir" "${venv_dir}.failed" || true
            fi
            mv "${venv_dir}.previous" "$venv_dir" || true
        fi
        systemctl daemon-reload || true
        systemctl restart wechat-sender.service || true
    fi
    rm -f "$unit_backup"
    exit "$rc"
}
trap rollback EXIT
trap 'rollback 129' HUP
trap 'rollback 130' INT
trap 'rollback 143' TERM

git -C "$install_dir" fetch --force origin '+refs/heads/*:refs/remotes/origin/*' </dev/null
git -C "$install_dir" cat-file -e "$target_commit^{commit}"
git -C "$install_dir" checkout --quiet --detach "$target_commit"
"$install_dir/scripts/install_wechat_sender.sh" --target-commit "$target_commit" </dev/null
"$install_dir/scripts/install_wechat_sender.sh" --apply --target-commit "$target_commit" </dev/null

if [ -f "$legacy_file" ]; then
    if command -v shred >/dev/null 2>&1; then
        shred --remove --zero "$legacy_file"
    else
        rm -f "$legacy_file"
    fi
fi
current_commit="$target_commit"
rm -f "$unit_backup"
trap - EXIT HUP INT TERM
health
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Operate the production WeChat sender.")
    parser.add_argument("--operation", choices=("health", "dry-run", "apply"), required=True)
    parser.add_argument("--target-commit", default="HEAD")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    target_commit = resolve_target_commit(args.target_commit)
    runtime = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    sender = runtime["managed_services"]["wechat_sender"]
    remote = sender_remote()
    command = [
        *ssh_command(remote),
        "sudo",
        "-n",
        "bash",
        "-s",
        "--",
        target_commit,
        args.operation,
        "/opt/wechat-on-airflow",
        str(sender["credential_directory"]),
    ]
    result = run(command, check=False, input_text=remote_script())
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise OpsError(detail[-1] if detail else "sender operation failed")
    payload = parse_remote_result(result.stdout)
    emit(payload, args.format)
    if payload.get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"deploy-wechat-sender: {exc}")
        raise SystemExit(1) from exc
