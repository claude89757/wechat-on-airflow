#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, emit, run, sender_remote, ssh_command

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REMOTE_BUNDLE_PREFIX = "/tmp/wechat-sender-"


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


def safe_dependency_preflight(value: dict[str, Any]) -> dict[str, Any] | None:
    """Keep failure inventory without publishing arbitrary remote text or stderr."""
    if value.get("stage") != "sender_dependency_preflight":
        return None
    clean: dict[str, Any] = {"stage": "sender_dependency_preflight"}
    for key in (
        "ok",
        "applied",
        "supported_interpreter",
        "rollback_environment_available",
        "active_environment_changed",
        "service_enabled",
        "service_active",
        "service_interpreter_matches",
        "service_ready",
        "active_pillow_inside_prefix",
        "disk_sufficient",
        "candidate_locked_dependencies_verified",
        "temporary_environment_removed",
        "candidate_pip_tag_inventory_available",
        "candidate_pip_arm32_tags",
        "candidate_pip_arm64_tags",
        "candidate_pip_native_cpython_abi",
        "candidate_pillow_arm32_source",
    ):
        if key in value:
            clean[key] = value[key] is True
    for key in (
        "free_bytes",
        "minimum_free_bytes",
        "external_test_sends",
        "active_python_bits",
        "candidate_python_bits",
    ):
        raw = value.get(key)
        if isinstance(raw, int) and not isinstance(raw, bool) and 0 <= raw <= 10**18:
            clean[key] = raw
    for key in ("current_commit", "target_commit", "runtime_commit"):
        raw = value.get(key)
        clean[key] = raw if isinstance(raw, str) and COMMIT_PATTERN.fullmatch(raw) else None
    for key in (
        "architecture",
        "active_python",
        "active_pillow",
        "candidate_pillow",
        "candidate_python",
        "active_python_platform",
        "candidate_python_platform",
    ):
        raw = value.get(key)
        if isinstance(raw, str) and re.fullmatch(r"[A-Za-z0-9_.+-]{1,40}", raw):
            clean[key] = raw
    for section, keys in (("distribution", ("ID", "VERSION_ID")), ("libc", ("name", "version"))):
        raw = value.get(section)
        if isinstance(raw, dict):
            clean[section] = {
                key: raw[key]
                for key in keys
                if isinstance(raw.get(key), str) and re.fullmatch(r"[A-Za-z0-9_.-]{0,40}", raw[key])
            }
    pip_version = value.get("candidate_pip_version")
    if (
        isinstance(pip_version, str)
        and len(pip_version) <= 40
        and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", pip_version)
    ):
        clean["candidate_pip_version"] = pip_version
    install_kind = value.get("candidate_install_failure_kind")
    if install_kind is not None:
        clean["candidate_install_failure_kind"] = (
            install_kind
            if isinstance(install_kind, str)
            and install_kind
            in {
                "no_matching_distribution",
                "network_tls",
                "network_connection",
                "index_authentication",
                "dependency_resolution",
                "build_failed",
                "timeout",
                "process_start_failed",
                "unclassified",
            }
            else "unclassified"
        )
    install_exit = value.get("candidate_install_exit_code")
    if type(install_exit) is int and -255 <= install_exit <= 255:
        clean["candidate_install_exit_code"] = install_exit
    failed_requirement = value.get("candidate_failed_requirement")
    if isinstance(failed_requirement, str):
        try:
            locked = {
                line.strip()
                for line in (REPO_ROOT / "docker/sender/requirements.lock").read_text().splitlines()
            }
        except OSError:
            locked = set()
        if failed_requirement in locked and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}==[A-Za-z0-9][A-Za-z0-9_.+!-]{0,39}",
            failed_requirement,
        ):
            clean["candidate_failed_requirement"] = failed_requirement
    category = value.get("failure_category")
    categories = {
        "service_not_enabled",
        "service_not_active",
        "service_interpreter_unknown",
        "active_service_or_rollback_unavailable",
        "sender_not_ready",
        "runtime_identity_mismatch",
        "active_dependency_inventory_failed",
        "unsupported_service_python",
        "service_python_venv_unavailable",
        "insufficient_staging_disk",
        "candidate_lock_unavailable",
        "candidate_checker_unavailable",
        "candidate_pillow_pin_invalid",
        "candidate_venv_failed",
        "candidate_interpreter_mismatch",
        "candidate_locked_install_failed",
        "candidate_dependency_conflict",
        "candidate_image_smoke_failed",
        "dependency_preflight_internal_error",
    }
    if category is not None:
        clean["failure_category"] = (
            category
            if isinstance(category, str) and category in categories
            else "unclassified_preflight_failure"
        )
    return clean


def create_deployment_bundle(path: Path) -> None:
    run(
        [
            "git",
            "bundle",
            "create",
            str(path),
            "refs/remotes/origin/main",
        ]
    )
    run(["git", "bundle", "verify", str(path)])


def upload_deployment_bundle(
    path: Path,
    remote: dict[str, str],
    remote_path: str,
) -> None:
    run(
        [
            "scp",
            "-q",
            "-o",
            "BatchMode=yes",
            "-o",
            "PreferredAuthentications=publickey",
            "-o",
            "PasswordAuthentication=no",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=15",
            "-P",
            remote["port"],
            str(path),
            f"{remote['username']}@{remote['host']}:{remote_path}",
        ]
    )


def remote_script() -> str:
    script = r"""
set -eu
target_commit="$1"
mode="$2"
install_dir="$3"
credential_dir="$4"
bundle_path="${5:-}"
service_file="/etc/systemd/system/wechat-sender.service"
venv_dir="/opt/wechat-sender-venv"

cleanup_bundle() {
    if [ -n "$bundle_path" ]; then
        rm -f -- "$bundle_path"
    fi
}

if [ -n "$bundle_path" ]; then
    case "$bundle_path" in
        /tmp/wechat-sender-*.bundle) ;;
        *) exit 2 ;;
    esac
fi
trap cleanup_bundle EXIT HUP INT TERM

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
    dependencies_ready=false
    if "$venv_dir/bin/python" "$install_dir/sender_agent/verify_dependencies.py" \
        "$install_dir/docker/sender/requirements.lock" >/dev/null 2>&1; then
        dependencies_ready=true
    fi
    python3 - "$current_commit" "$service_enabled" "$service_active" "$ready" \
        "$credential_dir" "$dependencies_ready" <<'PY'
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
        and sys.argv[6] == "true"
    ),
    "commit": sys.argv[1] or None,
    "service_enabled": sys.argv[2] == "enabled",
    "service_active": sys.argv[3] == "active",
    "ready": sys.argv[4] == "true",
    "dependencies_ready": sys.argv[6] == "true",
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
    ui_dump_file="$(mktemp)"
    remote_ui_dump="/data/local/tmp/wechat-sender-ui-$$.xml"
    if adb -s "$configured_device" shell uiautomator dump --compressed \
        "$remote_ui_dump" >/dev/null 2>&1; then
        adb -s "$configured_device" exec-out cat "$remote_ui_dump" \
            >"$ui_dump_file" 2>/dev/null || true
    fi
    adb -s "$configured_device" shell rm -f "$remote_ui_dump" >/dev/null 2>&1 || true
    current_focus="$(adb -s "$configured_device" shell dumpsys activity activities \
        2>/dev/null | grep -m 1 -E 'topResumedActivity|mResumedActivity' || true)"
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

    ADB_OUTPUT="$adb_output" READY_PAYLOAD="$ready_payload" \
        UI_DUMP_FILE="$ui_dump_file" CURRENT_FOCUS="$current_focus" python3 - \
        "$service_enabled" "$service_active" "$appium_active" "$adb_rc" \
        "$configured_state" "$usb_adb_interfaces" <<'PY'
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def ui_role(value):
    return {
        "搜索": "search",
        "取消": "cancel",
        "微信": "chats_tab",
        "通讯录": "contacts_tab",
        "发现": "discover_tab",
        "我": "me_tab",
    }.get(value)


def sanitized_node(node):
    attributes = node.attrib
    return {
        "class": attributes.get("class"),
        "resource_id": attributes.get("resource-id"),
        "bounds": attributes.get("bounds"),
        "clickable": attributes.get("clickable") == "true",
        "focused": attributes.get("focused") == "true",
        "text_role": ui_role(attributes.get("text")),
        "description_role": ui_role(attributes.get("content-desc")),
        "has_text": bool(attributes.get("text")),
        "has_description": bool(attributes.get("content-desc")),
    }


def parse_ui_snapshot(path):
    snapshot = {
        "dump_available": False,
        "node_count": 0,
        "top_clickable_controls": [],
        "search_controls": [],
        "edit_inputs": [],
    }
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return snapshot
    finally:
        path.unlink(missing_ok=True)
    xml_start = raw.find("<?xml")
    if xml_start < 0:
        return snapshot
    try:
        root = ET.fromstring(raw[xml_start:])
    except ET.ParseError:
        return snapshot

    nodes = list(root.iter("node"))
    snapshot["dump_available"] = True
    snapshot["node_count"] = len(nodes)
    parsed_bounds = []
    for node in nodes:
        match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.attrib.get("bounds", ""))
        if match:
            parsed_bounds.append((node, tuple(map(int, match.groups()))))
    screen_bottom = max((bounds[3] for _node, bounds in parsed_bounds), default=0)
    for node, bounds in parsed_bounds:
        details = sanitized_node(node)
        text_role = details["text_role"]
        description_role = details["description_role"]
        if text_role == "search" or description_role == "search":
            snapshot["search_controls"].append(details)
        if str(node.attrib.get("class", "")).endswith("EditText"):
            snapshot["edit_inputs"].append(details)
        center_y = (bounds[1] + bounds[3]) / 2
        if (
            node.attrib.get("clickable") == "true"
            and screen_bottom
            and center_y <= screen_bottom * 0.20
            and len(snapshot["top_clickable_controls"]) < 20
        ):
            snapshot["top_clickable_controls"].append(details)
    return snapshot


def parse_current_activity(value):
    match = re.search(r" ([A-Za-z0-9._]+/[A-Za-z0-9._$]+)(?:[ }]|$)", value)
    return match.group(1) if match else None

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
    "ui": {
        "current_activity": parse_current_activity(os.environ.pop("CURRENT_FOCUS", "")),
        **parse_ui_snapshot(Path(os.environ.pop("UI_DUMP_FILE"))),
    },
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

fetch_target() {
    test -n "$bundle_path"
    test -f "$bundle_path"
    git -C "$install_dir" fetch --quiet --force "$bundle_path" \
        'refs/remotes/origin/main:refs/remotes/origin/main' </dev/null
    git -C "$install_dir" cat-file -e "$target_commit^{commit}"
}

dependency_preflight() {
    python3 - "$current_commit" "$target_commit" "$install_dir" "$venv_dir" <<'DEPENDENCY_PREFLIGHT_PY'
import json
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

current_commit, target_commit, install_dir, venv_dir = sys.argv[1:]
minimum_free_bytes = 1024 * 1024 * 1024
report = {
    "stage": "sender_dependency_preflight",
    "ok": False,
    "applied": False,
    "current_commit": current_commit or None,
    "target_commit": target_commit,
    "architecture": platform.machine() if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", platform.machine()) else "unknown",
    "supported_interpreter": False,
    "rollback_environment_available": Path(venv_dir, "bin/python").is_file(),
    "active_environment_changed": False,
    "external_test_sends": 0,
}

class PreflightFailure(Exception):
    pass

def install_failure_diagnostics(stdout, stderr, lock_text, returncode=None, exception_kind=None):
    # Inspect only bounded captured text; emit fixed categories and known lock pins.
    output = (str(stdout or "") + "\n" + str(stderr or ""))[-65536:]
    lowered = output.lower()
    kind = exception_kind or "unclassified"
    signatures = (
        ("network_tls", ("certificate_verify_failed", "sslerror", "tlsv1", "certificate verify failed")),
        ("index_authentication", ("401 client error", "403 client error", "401 error", "403 error", "authentication required")),
        ("network_connection", ("connectionerror", "newconnectionerror", "connection refused", "temporary failure in name resolution", "network is unreachable", "readtimeout", "connecttimeout", "connection timed out", "max retries exceeded")),
        ("no_matching_distribution", ("no matching distribution found", "could not find a version that satisfies the requirement", "is not a supported wheel on this platform")),
        ("dependency_resolution", ("resolutionimpossible", "conflicting dependencies", "dependency conflict")),
        ("build_failed", ("failed building wheel", "could not build wheels", "metadata-generation-failed", "getting requirements to build wheel did not run successfully")),
    )
    if exception_kind is None:
        for category, markers in signatures:
            if any(marker in lowered for marker in markers):
                kind = category
                break
    result = {"candidate_install_failure_kind": kind}
    if type(returncode) is int and -255 <= returncode <= 255:
        result["candidate_install_exit_code"] = returncode
    locked = {}
    for line in lock_text.splitlines():
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]{0,79})==([A-Za-z0-9][A-Za-z0-9_.+!-]{0,39})", line.strip())
        if match:
            name, version = match.groups()
            locked[(re.sub(r"[-_.]+", "-", name).lower(), version)] = line.strip()
    failed = set()
    for name, version in re.findall(r"(?:No matching distribution found for|Could not find a version that satisfies the requirement)\s+([A-Za-z0-9][A-Za-z0-9_.-]{0,79})==([A-Za-z0-9][A-Za-z0-9_.+!-]{0,39})(?=\s|\(|$)", output, re.IGNORECASE):
        pin = locked.get((re.sub(r"[-_.]+", "-", name).lower(), version))
        if pin:
            failed.add(pin)
    if len(failed) == 1:
        result["candidate_failed_requirement"] = next(iter(failed))
    return result

def record_install_failure(install_lock, stdout="", stderr="", returncode=None, exception_kind=None):
    if install_lock is None:
        return
    try:
        report.update(install_failure_diagnostics(stdout, stderr, install_lock.read_text(), returncode, exception_kind))
    except Exception:
        # Failure to collect optional diagnostics must not replace the install failure.
        report["candidate_install_failure_kind"] = exception_kind or "unclassified"
        if type(returncode) is int and -255 <= returncode <= 255:
            report["candidate_install_exit_code"] = returncode

def command(argv, category, timeout=30, install_lock=None):
    try:
        result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        record_install_failure(install_lock, exception_kind="timeout")
        raise PreflightFailure(category) from None
    except OSError:
        record_install_failure(install_lock, exception_kind="process_start_failed")
        raise PreflightFailure(category) from None
    if result.returncode != 0:
        record_install_failure(install_lock, result.stdout, result.stderr, result.returncode)
        raise PreflightFailure(category)
    return result.stdout.strip()

try:
    report["service_enabled"] = command(["systemctl", "is-enabled", "wechat-sender.service"], "service_not_enabled") == "enabled"
    report["service_active"] = command(["systemctl", "is-active", "wechat-sender.service"], "service_not_active") == "active"
    exec_start = command(["systemctl", "show", "wechat-sender.service", "--property=ExecStart", "--value"], "service_interpreter_unknown")
    report["service_interpreter_matches"] = re.search(r"(?:^|[ =])" + re.escape(str(Path(venv_dir, "bin/python"))) + r"(?=[ ;]|$)", exec_start) is not None
    if not all(report[key] for key in ("service_enabled", "service_active", "service_interpreter_matches", "rollback_environment_available")):
        raise PreflightFailure("active_service_or_rollback_unavailable")
    ready = json.loads(command(["curl", "--fail", "--silent", "--show-error", "--max-time", "5", "http://127.0.0.1:7001/readyz"], "sender_not_ready"))
    report["service_ready"] = isinstance(ready, dict) and ready.get("ok") is True
    runtime_commit = ready.get("deploymentCommit") if isinstance(ready, dict) else None
    report["runtime_commit"] = runtime_commit if re.fullmatch(r"[0-9a-f]{40}", str(runtime_commit)) else None
    if not report["service_ready"]:
        raise PreflightFailure("sender_not_ready")
    if report["runtime_commit"] != current_commit:
        raise PreflightFailure("runtime_identity_mismatch")
    active_probe = command([str(Path(venv_dir, "bin/python")), "-c", "import json,os,struct,sys,sysconfig; import PIL; prefix=os.path.realpath(sys.prefix); print(json.dumps({'python': '.'.join(map(str,sys.version_info[:3])), 'bits': struct.calcsize('P')*8, 'platform': sysconfig.get_platform(), 'pillow': PIL.__version__, 'inside_prefix': os.path.commonpath([os.path.realpath(PIL.__file__),prefix]) == prefix}))"], "active_dependency_inventory_failed")
    active = json.loads(active_probe)
    report["active_python"] = active.get("python") if re.fullmatch(r"[0-9.]{1,32}", str(active.get("python", ""))) else None
    report["active_pillow"] = active.get("pillow") if re.fullmatch(r"[A-Za-z0-9.+-]{1,40}", str(active.get("pillow", ""))) else None
    report["active_pillow_inside_prefix"] = active.get("inside_prefix") is True
    report["active_python_bits"] = active.get("bits") if active.get("bits") in (32, 64) else None
    report["active_python_platform"] = active.get("platform") if re.fullmatch(r"[A-Za-z0-9_.+-]{1,40}", str(active.get("platform", ""))) else None
    try:
        distro = getattr(platform, "freedesktop_os_release", lambda: {})()
        report["distribution"] = {}
        for key in ("ID", "VERSION_ID"):
            value = distro.get(key)
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", value):
                report["distribution"][key] = value
    except OSError:
        report["distribution"] = {}
    libc_name, libc_version = platform.libc_ver()
    report["libc"] = {"name": libc_name if re.fullmatch(r"[A-Za-z0-9_-]{0,32}", libc_name) else "unknown", "version": libc_version if re.fullmatch(r"[A-Za-z0-9_.-]{0,40}", libc_version) else "unknown"}
    # Never select a different minor from PATH: reuse the actual service interpreter.
    service_python = str(Path(venv_dir, "bin/python"))
    report["supported_interpreter"] = str(report["active_python"]).split(".")[:2] in (["3", "11"], ["3", "12"])
    if not report["supported_interpreter"]:
        raise PreflightFailure("unsupported_service_python")
    command([service_python, "-c", "import sys,venv; assert sys.version_info[:2] in {(3,11),(3,12)}"], "service_python_venv_unavailable")
    report["free_bytes"] = shutil.disk_usage(Path(venv_dir).parent).free
    report["minimum_free_bytes"] = minimum_free_bytes
    report["disk_sufficient"] = report["free_bytes"] >= minimum_free_bytes
    if not report["disk_sufficient"]:
        raise PreflightFailure("insufficient_staging_disk")
    # Stage on the active environment's filesystem, never in the live checkout.
    # TemporaryDirectory cleans up failures; raw pip/host output is never published.
    with tempfile.TemporaryDirectory(prefix=".sender-preflight-", dir=Path(venv_dir).parent) as directory:
        staging = Path(directory)
        lock = staging / "requirements.lock"
        checker = staging / "verify_dependencies.py"
        lock.write_text(command(["git", "-C", install_dir, "show", target_commit + ":docker/sender/requirements.lock"], "candidate_lock_unavailable") + "\n")
        checker.write_text(command(["git", "-C", install_dir, "show", target_commit + ":sender_agent/verify_dependencies.py"], "candidate_checker_unavailable") + "\n")
        pins = re.findall(r"^Pillow==([0-9]+(?:\.[0-9]+){2})$", lock.read_text(), re.MULTILINE)
        if len(pins) != 1:
            raise PreflightFailure("candidate_pillow_pin_invalid")
        report["candidate_pillow"] = pins[0]
        environment = staging / "venv"
        command([service_python, "-m", "venv", str(environment)], "candidate_venv_failed", 120)
        candidate_python = str(environment / "bin/python")
        candidate_probe = '''import contextlib,io,json,re,struct,sys,sysconfig
inventory = {'python': '.'.join(map(str,sys.version_info[:3])), 'bits': struct.calcsize('P')*8, 'platform': sysconfig.get_platform(), 'pip_tag_inventory_available': False}
# Optional evidence only: an inventory error never changes the installation policy.
try:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        import pip
        version = str(pip.__version__)
        if len(version) <= 40 and re.fullmatch(r'[0-9]+(?:\\.[0-9]+){1,3}', version):
            inventory['pip_version'] = version
        from pip._internal.utils.compatibility_tags import get_supported
        tags = get_supported()
    inventory['pip_tag_inventory_available'] = True
    inventory['pip_arm32_tags'] = any(tag.platform.endswith(('_armv6l', '_armv7l')) for tag in tags)
    inventory['pip_arm64_tags'] = any(tag.platform.endswith('_aarch64') for tag in tags)
    inventory['pip_native_cpython_abi'] = any(tag.abi == 'cp%d%d' % sys.version_info[:2] for tag in tags)
except (Exception, SystemExit):
    pass
print(json.dumps(inventory))'''
        candidate = json.loads(command([candidate_python, "-c", candidate_probe], "candidate_interpreter_mismatch"))
        if (str(candidate.get("python")).split(".")[:2] != str(active.get("python")).split(".")[:2]
                or candidate.get("bits") != active.get("bits") or candidate.get("platform") != active.get("platform")):
            raise PreflightFailure("candidate_interpreter_mismatch")
        report["candidate_python"] = candidate["python"]
        report["candidate_python_bits"] = candidate["bits"]
        report["candidate_python_platform"] = candidate["platform"]
        candidate_pip = candidate.get("pip_version")
        if isinstance(candidate_pip, str) and len(candidate_pip) <= 40 and re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", candidate_pip):
            report["candidate_pip_version"] = candidate_pip
        for key in ("pip_tag_inventory_available", "pip_arm32_tags", "pip_arm64_tags", "pip_native_cpython_abi"):
            report["candidate_" + key] = candidate.get(key) is True
        report["candidate_pillow_arm32_source"] = (
            candidate.get("bits") == 32
            and candidate.get("pip_tag_inventory_available") is True
            and candidate.get("pip_arm32_tags") is True
        )
        if report["candidate_pillow_arm32_source"]:
            # Scope the supplemental source to the already-validated Pillow pin.
            # All other packages keep the original full-lock discovery policy.
            command([candidate_python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "--only-binary=Pillow", "--no-deps", "--find-links", "https://www.piwheels.org/simple/pillow/", "Pillow==" + pins[0]], "candidate_locked_install_failed", 300, install_lock=lock)
        command([candidate_python, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", "--only-binary=Pillow", "--requirement", str(lock)], "candidate_locked_install_failed", 300, install_lock=lock)
        command([candidate_python, "-m", "pip", "check"], "candidate_dependency_conflict", 30)
        command([candidate_python, str(checker), str(lock)], "candidate_image_smoke_failed", 30)
        report["candidate_locked_dependencies_verified"] = True
    report["temporary_environment_removed"] = True
    report["ok"] = True
except PreflightFailure as exc:
    report["failure_category"] = str(exc)
except Exception:
    report["failure_category"] = "dependency_preflight_internal_error"
print(json.dumps(report, sort_keys=True))
raise SystemExit(0 if report["ok"] else 1)
DEPENDENCY_PREFLIGHT_PY
}

legacy_backup=""
preserve_reviewed_drift() {
    python3 - "$install_dir" "$mode" <<'LEGACY_PY'
__LEGACY_PATCH_HELPER__
LEGACY_PY
}

credentials_ready=false
if [ -s "$credential_dir/wechat_allowed_device_name" ] && \
   [ -s "$credential_dir/wechat_appium_url" ]; then
    credentials_ready=true
fi
if [ "$mode" = "dry-run" ]; then
    test "$credentials_ready" = true
    preserve_reviewed_drift >/dev/null
    fetch_target
    dependency_report="$(dependency_preflight)" || {
        rc="$?"
        printf '%s\n' "$dependency_report"
        exit "$rc"
    }
    python3 - "$current_commit" "$target_commit" "$dependency_report" <<'PY'
import json
import sys

print(json.dumps({
    "ok": True,
    "applied": False,
    "current_commit": sys.argv[1] or None,
    "target_commit": sys.argv[2],
    "credentials_ready": True,
    "dependency_preflight": json.loads(sys.argv[3]),
}, sort_keys=True))
PY
    exit 0
fi

test "$mode" = "apply"
test "$(id -u)" = 0
test "$credentials_ready" = true
fetch_target
dependency_preflight

# A retained .previous may belong to an earlier successful release. Restore it
# only after this attempt has actually moved/replaced the active environment.
venv_identity_before="$(stat -c '%d:%i' "$venv_dir" 2>/dev/null || true)"
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
        if [ -n "$legacy_backup" ] && [ -f "$legacy_backup" ]; then
            cp "$legacy_backup" "$install_dir/sender_agent/app.py" || true
        fi
        if [ -s "$unit_backup" ]; then
            cp -p "$unit_backup" "$service_file" || true
        fi
        venv_identity_after="$(stat -c '%d:%i' "$venv_dir" 2>/dev/null || true)"
        if [ "$venv_identity_after" != "$venv_identity_before" ]; then
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
    fi
    rm -f "$unit_backup"
    cleanup_bundle
    exit "$rc"
}
trap rollback EXIT
trap 'rollback 129' HUP
trap 'rollback 130' INT
trap 'rollback 143' TERM

legacy_backup="$(preserve_reviewed_drift)"
git -C "$install_dir" checkout --quiet --detach "$target_commit"
"$install_dir/scripts/install_wechat_sender.sh" --target-commit "$target_commit" </dev/null
"$install_dir/scripts/install_wechat_sender.sh" --apply --target-commit "$target_commit" </dev/null

current_commit="$target_commit"
rm -f "$unit_backup"
cleanup_bundle
trap - EXIT HUP INT TERM
health
"""
    helper = Path(__file__).with_name("preserve_sender_legacy_patch.py").read_text()
    return script.replace("__LEGACY_PATCH_HELPER__", helper)


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
    remote_bundle_path = ""
    with tempfile.TemporaryDirectory(prefix="wechat-sender-deploy-") as directory:
        if args.operation in {"dry-run", "apply"}:
            bundle_path = Path(directory) / "repository.bundle"
            create_deployment_bundle(bundle_path)
            remote_bundle_path = f"{REMOTE_BUNDLE_PREFIX}{uuid.uuid4().hex}.bundle"
            upload_deployment_bundle(bundle_path, remote, remote_bundle_path)

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
            remote_bundle_path,
        ]
        result = run(command, check=False, input_text=remote_script())
    if result.returncode:
        try:
            failure = parse_remote_result(result.stdout)
        except OpsError:
            failure = {}
        evidence = safe_dependency_preflight(failure)
        if evidence is not None:
            emit(evidence, args.format)
        # Remote stderr can include private hosts, package index URLs, or secrets.
        raise OpsError("sender operation failed; inspect sanitized preflight evidence when present")
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
