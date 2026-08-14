#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    raise OpsError("WeChat delivery diagnosis returned no structured result")


def remote_script() -> str:
    return r"""
set -eu
cd "$1"

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
compose exec -T "$api_service" python - <<'PY'
import json
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from airflow.models.variable import Variable


def chatrooms(name):
    value = str(Variable.get(name, default_var=""))
    return [item.strip() for item in value.splitlines() if item.strip()]


def error_category(value):
    text = str(value or "").lower()
    detail_signatures = (
        ("target chat was not verified", "chat_title_not_verified"),
        ("receiver did not open", "search_result_did_not_open"),
        ("unable to return to wechat search results", "search_return_failed"),
        ("wechat search page did not open", "search_page_did_not_open"),
        ("unable to return to wechat main page", "main_page_return_failed"),
    )
    for signature, category in detail_signatures:
        if signature in text:
            return category
    match = re.search(r"wechat send api failed: ([a-z0-9_]+):", text)
    if match:
        return match.group(1)
    if "request failed" in text:
        return "request_error"
    if "non-json response" in text:
        return "non_json_response"
    if "invalid json shape" in text:
        return "invalid_json_shape"
    return "unknown"


targets = {
    "general": chatrooms("SZ_TENNIS_CHATROOMS"),
    "tyzx": chatrooms("SZ_TYZX_TENNIS_CHATROOMS"),
}
positions = {}
for target_set, values in targets.items():
    for index, receiver in enumerate(values, start=1):
        positions.setdefault(receiver, []).append((target_set, index))

try:
    outbox = Variable.get(
        "WECHAT_SEND_FALLBACK_OUTBOX", default_var=[], deserialize_json=True
    )
except Exception:
    outbox = None

cutoff = datetime.now(UTC) - timedelta(hours=24)
groups = defaultdict(lambda: {"entries": 0, "attempts": 0, "latest_failed_at": None})
recent_entries = 0
if isinstance(outbox, list):
    for item in outbox:
        if not isinstance(item, dict):
            continue
        timestamp = item.get("last_failed_at")
        try:
            failed_at = datetime.fromisoformat(str(timestamp)).astimezone(UTC)
        except (TypeError, ValueError):
            continue
        if failed_at < cutoff:
            continue
        recent_entries += 1
        receiver_positions = positions.get(str(item.get("receiver") or "")) or [
            ("unconfigured", None)
        ]
        category = error_category(item.get("error"))
        for target_set, target_index in receiver_positions:
            key = (target_set, target_index, category)
            group = groups[key]
            group["entries"] += 1
            group["attempts"] += max(int(item.get("attempt_count") or 0), 0)
            current_latest = group["latest_failed_at"]
            if current_latest is None or failed_at.isoformat() > current_latest:
                group["latest_failed_at"] = failed_at.isoformat()

failures = [
    {
        "target_set": target_set,
        "target_index": target_index,
        "error_category": category,
        **details,
    }
    for (target_set, target_index, category), details in sorted(
        groups.items(), key=lambda item: (item[0][0], item[0][1] or 0, item[0][2])
    )
]
print(
    json.dumps(
        {
            "ok": isinstance(outbox, list),
            "read_only": True,
            "window_hours": 24,
            "configured_target_counts": {
                name: len(values) for name, values in targets.items()
            },
            "outbox_count": len(outbox) if isinstance(outbox, list) else None,
            "recent_failure_entries": recent_entries,
            "failures": failures,
        },
        sort_keys=True,
    )
)
PY
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose recent WeChat delivery failures without exposing content."
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    remote = airflow_remote()
    result = run(
        [
            *ssh_command(remote),
            "bash",
            "-s",
            "--",
            remote["repository_path"],
        ],
        check=False,
        input_text=remote_script(),
    )
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        raise OpsError(detail[-1] if detail else "WeChat delivery diagnosis failed")
    payload = parse_remote_result(result.stdout)
    emit(payload, args.format)
    if payload.get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"diagnose-wechat-delivery: {exc}")
        raise SystemExit(1) from exc
