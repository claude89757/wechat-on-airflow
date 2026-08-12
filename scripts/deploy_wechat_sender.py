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
        "$credential_dir" <<'PY'
import json
import stat
import sys
from pathlib import Path

directory = Path(sys.argv[5])
expected_files = ("wechat_allowed_device_name", "wechat_appium_url")
try:
    directory_stat = directory.stat()
    directory_ready = (
        directory.is_dir()
        and stat.S_IMODE(directory_stat.st_mode) == 0o700
        and directory_stat.st_uid == 0
        and directory_stat.st_gid == 0
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
            "owned_by_root": details.st_uid == 0 and details.st_gid == 0,
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

print(json.dumps({
    "ok": (
        sys.argv[2] == "enabled"
        and sys.argv[3] == "active"
        and sys.argv[4] == "true"
        and credentials_ready
    ),
    "commit": sys.argv[1] or None,
    "service_enabled": sys.argv[2] == "enabled",
    "service_active": sys.argv[3] == "active",
    "ready": sys.argv[4] == "true",
    "credentials": {
        "ready": credentials_ready,
        "directory_ready": directory_ready,
        "files": files,
    },
}, sort_keys=True))
PY
}

device_state() {
    service_enabled="$(systemctl is-enabled wechat-sender.service 2>/dev/null || true)"
    service_active="$(systemctl is-active wechat-sender.service 2>/dev/null || true)"
    appium_active="$(systemctl is-active appium-6002.service 2>/dev/null || true)"
    adb_rc=0
    adb_output="$(adb devices 2>&1)" || adb_rc="$?"
    configured_device="$(tr -d '\r\n' < "$credential_dir/wechat_allowed_device_name")"
    configured_state="$(adb -s "$configured_device" get-state 2>/dev/null || true)"
    ready_payload="$(curl --silent --show-error --max-time 5 \
        http://127.0.0.1:7001/readyz 2>/dev/null || true)"
    usb_adb_interfaces=0
    for interface in /sys/bus/usb/devices/*:*; do
        [ -r "$interface/bInterfaceClass" ] || continue
        interface_class="$(tr '[:upper:]' '[:lower:]' < "$interface/bInterfaceClass")"
        interface_subclass="$(tr '[:upper:]' '[:lower:]' < "$interface/bInterfaceSubClass")"
        interface_protocol="$(tr '[:upper:]' '[:lower:]' < "$interface/bInterfaceProtocol")"
        if [ "$interface_class" = "ff" ] && \
           [ "$interface_subclass" = "42" ] && \
           [ "$interface_protocol" = "01" ]; then
            usb_adb_interfaces=$((usb_adb_interfaces + 1))
        fi
    done

    ADB_OUTPUT="$adb_output" READY_PAYLOAD="$ready_payload" python3 - \
        "$service_enabled" "$service_active" "$appium_active" "$adb_rc" \
        "$configured_state" "$usb_adb_interfaces" <<'PY'
import json
import os
import sys

counts = {"device": 0, "offline": 0, "unauthorized": 0, "other": 0}
for line in os.environ.pop("ADB_OUTPUT", "").splitlines():
    if "\t" not in line:
        continue
    _, state = line.split("\t", 1)
    state = state.strip().split(maxsplit=1)[0]
    counts[state if state in counts else "other"] += 1

try:
    readiness = json.loads(os.environ.pop("READY_PAYLOAD", ""))
except (json.JSONDecodeError, TypeError):
    readiness = {}
if not isinstance(readiness, dict):
    readiness = {}

service_enabled = sys.argv[1] == "enabled"
service_active = sys.argv[2] == "active"
appium_active = sys.argv[3] == "active"
adb_command_ok = sys.argv[4] == "0"
configured_device_online = sys.argv[5] == "device"
usb_adb_interface_count = int(sys.argv[6])
ready = readiness.get("ok") is True
readiness_error = readiness.get("error")
if not isinstance(readiness_error, str):
    readiness_error = None

failure_category = None
if not ready:
    if not service_active:
        failure_category = "sender_service_inactive"
    elif not appium_active:
        failure_category = "appium_service_inactive"
    elif not adb_command_ok:
        failure_category = "adb_command_failed"
    elif counts["unauthorized"]:
        failure_category = "adb_device_unauthorized"
    elif counts["offline"]:
        failure_category = "adb_device_offline"
    elif counts["device"] == 0 and usb_adb_interface_count == 0:
        failure_category = "adb_usb_interface_absent"
    elif counts["device"] == 0:
        failure_category = "adb_device_not_enumerated"
    elif not configured_device_online:
        failure_category = "configured_device_not_online"
    else:
        failure_category = readiness_error or "sender_not_ready"

print(json.dumps({
    "ok": True,
    "read_only": True,
    "ready": ready,
    "service_enabled": service_enabled,
    "service_active": service_active,
    "appium_active": appium_active,
    "adb": {
        "command_ok": adb_command_ok,
        "state_counts": counts,
        "configured_device_online": configured_device_online,
    },
    "usb_adb_interface_count": usb_adb_interface_count,
    "readiness_error": readiness_error,
    "failure_category": failure_category,
}, sort_keys=True))
PY
}

recover_device() {
    before="$(device_state)"
    systemctl stop wechat-sender.service
    systemctl stop appium-6002.service
    adb kill-server >/dev/null 2>&1 || true
    udevadm settle --timeout=10 >/dev/null 2>&1 || true
    adb start-server >/dev/null 2>&1
    adb reconnect >/dev/null 2>&1 || true
    systemctl start appium-6002.service
    systemctl start wechat-sender.service
    attempt=0
    while [ "$attempt" -lt 12 ]; do
        if curl --fail --silent --show-error --max-time 5 \
            http://127.0.0.1:7001/readyz >/dev/null 2>&1; then
            break
        fi
        attempt=$((attempt + 1))
        sleep 5
    done
    after="$(device_state)"
    BEFORE="$before" AFTER="$after" python3 - <<'PY'
import json
import os

before = json.loads(os.environ.pop("BEFORE"))
after = json.loads(os.environ.pop("AFTER"))
print(json.dumps({
    "ok": after.get("ready") is True,
    "applied": True,
    "phone_rebooted": False,
    "notification_sent": False,
    "actions": [
        "restart_adb_server",
        "settle_usb_devices",
        "restart_appium_service",
        "restart_sender_service",
        "wait_for_readiness",
    ],
    "before": before,
    "after": after,
}, sort_keys=True))
PY
}

if [ "$mode" = "health" ]; then
    health
    exit 0
fi
if [ "$mode" = "device-diagnose" ]; then
    device_state
    exit 0
fi
if [ "$mode" = "device-recover" ]; then
    recover_device
    exit 0
fi

credentials_ready=false
if [ -s "$credential_dir/wechat_allowed_device_name" ] && \
   [ -s "$credential_dir/wechat_appium_url" ]; then
    credentials_ready=true
fi
if [ "$mode" = "dry-run" ]; then
    test "$credentials_ready" = true
    git -C "$install_dir" fetch --quiet origin </dev/null
    git -C "$install_dir" cat-file -e "$target_commit^{commit}"
    python3 - "$current_commit" "$target_commit" <<'PY'
import json
import sys

print(json.dumps({
    "ok": True,
    "applied": False,
    "current_commit": sys.argv[1] or None,
    "target_commit": sys.argv[2],
    "credentials_ready": True,
}, sort_keys=True))
PY
    exit 0
fi

test "$mode" = "apply"
test "$(id -u)" = 0
test "$credentials_ready" = true

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

current_commit="$target_commit"
rm -f "$unit_backup"
trap - EXIT HUP INT TERM
health
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Operate the production WeChat sender.")
    parser.add_argument(
        "--operation",
        choices=("health", "dry-run", "apply", "device-diagnose", "device-recover"),
        required=True,
    )
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
