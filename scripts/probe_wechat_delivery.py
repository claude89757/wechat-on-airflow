#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from _ops import OpsError, airflow_remote, emit, run, ssh_command


def parse_remote_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise OpsError("WeChat delivery probe returned no structured result")


def remote_script() -> str:
    return r"""
set -eu
cd "$1"
test "$2" = "real-send-approved"

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        return 127
    fi
}

api_service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
test -n "$api_service"
compose exec -T -e "PROBE_TARGET_MEMBERSHIP=$3" "$api_service" python - <<'PY'
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier, Lock

import requests
from airflow.models.variable import Variable


def variable(name, default=""):
    return Variable.get(name, default_var=default)


def integer_variable(name, default):
    try:
        return int(variable(name, str(default)))
    except (TypeError, ValueError):
        return default


def float_variable(name, default):
    try:
        return float(variable(name, str(default)))
    except (TypeError, ValueError):
        return default


def chatrooms(name):
    return [item.strip() for item in str(variable(name, "")).splitlines() if item.strip()]


configured = {
    "general": chatrooms("SZ_TENNIS_CHATROOMS"),
    "tyzx": chatrooms("SZ_TYZX_TENNIS_CHATROOMS"),
}
targets = []
by_receiver = {}
for target_set, receivers in configured.items():
    for target_index, receiver in enumerate(receivers, start=1):
        existing = by_receiver.get(receiver)
        membership = {"target_set": target_set, "target_index": target_index}
        if existing is not None:
            existing["memberships"].append(membership)
            continue
        target = {
            "receiver": receiver,
            "memberships": [membership],
            "ordinal": len(targets) + 1,
        }
        targets.append(target)
        by_receiver[receiver] = target

selector = os.environ.get("PROBE_TARGET_MEMBERSHIP", "").strip()
if selector == "all":
    selector = ""
if selector:
    selected_set, selected_index = selector.split(":", 1)
    selected_membership = {
        "target_set": selected_set,
        "target_index": int(selected_index),
    }
    targets = [
        target for target in targets if selected_membership in target["memberships"]
    ]

if not targets:
    print(json.dumps({"ok": False, "error": "no_configured_targets"}, sort_keys=True))
    raise SystemExit(0)

general = [target for target in targets if target["memberships"][0]["target_set"] == "general"]
tyzx_only = [target for target in targets if target not in general]
if general and tyzx_only:
    lanes = [general, tyzx_only]
else:
    lanes = [targets[::2], targets[1::2]]
lanes = [lane for lane in lanes if lane]

api_url = str(variable("WECHAT_SEND_API_URL", "")).strip()
device_name = str(variable("WECHAT_SEND_DEVICE_NAME", "")).strip()
timeout_seconds = max(integer_variable("WECHAT_SEND_TIMEOUT_SECONDS", 120), 1)
retry_count = max(integer_variable("WECHAT_SEND_RETRY_COUNT", 3), 1)
retry_delay_seconds = max(float_variable("WECHAT_SEND_RETRY_DELAY_SECONDS", 5.0), 0)
if not api_url or not device_name:
    print(json.dumps({"ok": False, "error": "sender_configuration_missing"}, sort_keys=True))
    raise SystemExit(0)

sent_at = datetime.now(UTC).replace(microsecond=0)
message = (
    "【系统验收】微信并发发送链路测试，发送时间："
    f"{sent_at.isoformat()}。无需回复。"
)
barrier = Barrier(len(lanes))
result_lock = Lock()
results = []
lane_started = []


def send_target(target, lane_index):
    started = time.monotonic()
    error_category = None
    status_code = None
    for attempt in range(1, retry_count + 1):
        try:
            response = requests.post(
                api_url,
                json={
                    "receiver": target["receiver"],
                    "messages": [message],
                    "device_name": device_name,
                },
                timeout=timeout_seconds,
            )
            status_code = response.status_code
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if (
                response.status_code < 400
                and isinstance(payload, dict)
                and payload.get("success") is True
            ):
                return {
                    "success": True,
                    "lane": lane_index,
                    "ordinal": target["ordinal"],
                    "memberships": target["memberships"],
                    "attempts": attempt,
                    "navigation_path": payload.get("navigation_path", "unknown"),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            if isinstance(payload, dict) and isinstance(payload.get("error"), str):
                error_category = payload["error"]
            else:
                error_category = f"http_{response.status_code}"
        except requests.RequestException:
            error_category = "request_error"
        if attempt < retry_count:
            time.sleep(retry_delay_seconds)
    return {
        "success": False,
        "lane": lane_index,
        "ordinal": target["ordinal"],
        "memberships": target["memberships"],
        "attempts": retry_count,
        "status_code": status_code,
        "error_category": error_category or "unknown",
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def run_lane(lane_index, lane):
    barrier.wait(timeout=10)
    with result_lock:
        lane_started.append(time.monotonic())
    lane_results = [send_target(target, lane_index) for target in lane]
    with result_lock:
        results.extend(lane_results)


with ThreadPoolExecutor(max_workers=len(lanes)) as executor:
    futures = [
        executor.submit(run_lane, lane_index, lane)
        for lane_index, lane in enumerate(lanes, start=1)
    ]
    for future in futures:
        future.result()

results.sort(key=lambda item: item["ordinal"])
success_count = sum(1 for item in results if item["success"])
start_spread_ms = (
    round((max(lane_started) - min(lane_started)) * 1000, 3)
    if len(lane_started) > 1
    else 0
)
print(
    json.dumps(
        {
            "ok": success_count == len(targets),
            "real_send": True,
            "message_kind": "concurrent_delivery_acceptance",
            "target_selector": selector or None,
            "sent_at": sent_at.isoformat(),
            "configured_target_counts": {
                name: len(values) for name, values in configured.items()
            },
            "unique_target_count": len(targets),
            "lane_count": len(lanes),
            "lane_start_spread_ms": start_spread_ms,
            "success_count": success_count,
            "failure_count": len(targets) - success_count,
            "results": results,
        },
        sort_keys=True,
    )
)
PY
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send one approved concurrent acceptance message to configured WeChat chats."
    )
    parser.add_argument("--confirm-real-send", action="store_true")
    parser.add_argument("--target-membership", default="")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    if not args.confirm_real_send:
        raise OpsError("real WeChat delivery requires --confirm-real-send")
    if args.target_membership not in ("", "all") and not re.fullmatch(
        r"(?:general|tyzx):[1-9][0-9]*", args.target_membership
    ):
        raise OpsError("target membership must match general:N or tyzx:N")

    remote = airflow_remote()
    result = run(
        [
            *ssh_command(remote),
            "bash",
            "-s",
            "--",
            remote["repository_path"],
            "real-send-approved",
            args.target_membership,
        ],
        check=False,
        input_text=remote_script(),
    )
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise OpsError(detail[-1] if detail else "WeChat delivery probe failed")
    payload = parse_remote_result(result.stdout)
    emit(payload, args.format)
    if payload.get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"probe-wechat-delivery: {exc}")
        raise SystemExit(1) from exc
