#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

from _ops import OpsError, airflow_remote, emit, run, ssh_command

DAG_ID = "zacks_phone_daily_reboot"


def parse_remote_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise OpsError("phone diagnostic did not return structured output")


def redact_error(value: str) -> str:
    redacted = re.sub(
        r"(?i)(password|authorization|access[_ -]?token|secret|fernet[_ -]?key)"
        r"([\"']?\s*[:=]\s*)([\"']?)([^\s,}\]]+)",
        r"\1\2<redacted>",
        value,
    )
    redacted = re.sub(
        r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+@",
        r"\1<redacted>@",
        redacted,
    )
    return redacted[-600:]


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
        printf 'docker compose is unavailable\n' >&2
        return 127
    fi
}
service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
test -n "$service"
compose exec -T "$service" python - <<'PY'
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO

from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.utils.log.log_reader import TaskLogReader
from airflow.utils.session import create_session

from wechat_airflow.clients.android_device import (
    build_login_shell_adb_command,
    exec_cmd_by_ssh_with_status,
)
from wechat_airflow.maintenance.zacks_phone_reboot import load_zacks_device_config

DAG_ID = "zacks_phone_daily_reboot"
SIGNAL = re.compile(
    r"traceback|error|exception|failed|failure|timeout|timed out|refused|"
    r"unreachable|host key|adb|reboot|ssh",
    re.IGNORECASE,
)
SECRET = re.compile(
    r"(?i)(password|authorization|access[_ -]?token|secret|fernet[_ -]?key)"
    r"([\"']?\s*[:=]\s*)([\"']?)([^\s,}\]]+)",
)
DATABASE_URL = re.compile(r"(?i)([a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+@")


def timestamp(value):
    return value.isoformat() if value is not None else None


def sanitize(line):
    line = DATABASE_URL.sub(r"\1<redacted>@", line)
    line = SECRET.sub(r"\1\2<redacted>", line)
    return line[-600:]


with create_session() as session:
    run = (
        session.query(DagRun)
        .filter(DagRun.dag_id == DAG_ID, DagRun.state == "failed")
        .order_by(DagRun.id.desc())
        .first()
    )
    if run is None:
        print(json.dumps({"ok": True, "dag_id": DAG_ID, "latest_failed_run": None}))
        raise SystemExit(0)

    instances = (
        session.query(TaskInstance)
        .filter(TaskInstance.dag_id == DAG_ID, TaskInstance.run_id == run.run_id)
        .order_by(TaskInstance.task_id.asc())
        .all()
    )
    task_rows = [
        {
            "task_id": item.task_id,
            "state": str(item.state),
            "try_number": int(item.try_number or 0),
            "max_tries": int(item.max_tries or 0),
            "started_at": timestamp(item.start_date),
            "ended_at": timestamp(item.end_date),
        }
        for item in instances
    ]

    evidence = []
    reader = TaskLogReader()
    for instance, task in zip(instances, task_rows, strict=True):
        if task["state"].lower() != "failed" or task["try_number"] < 1:
            continue
        signatures = []
        messages_examined = 0
        read_errors = []
        for attempt in range(1, task["try_number"] + 1):
            try:
                stream, _ = reader.read_log_chunks(instance, attempt, {})
                lines = [str(message.event) for message in stream]
            except Exception as exc:
                read_errors.append(type(exc).__name__)
                continue
            messages_examined += len(lines)
            for line in lines[-400:]:
                if SIGNAL.search(line):
                    sanitized = sanitize(line)
                    if sanitized not in signatures:
                        signatures.append(sanitized)
        evidence.append(
            {
                "task_id": task["task_id"],
                "log_messages_examined": messages_examined,
                "log_read_errors": sorted(set(read_errors)),
                "error_signatures": signatures[-40:],
            }
        )

    run_row = {
        "run_id": run.run_id,
        "state": str(run.state),
        "logical_date": timestamp(run.logical_date),
        "started_at": timestamp(run.start_date),
        "ended_at": timestamp(run.end_date),
    }

probe = {
    "configuration_valid": False,
    "ssh_connected": False,
    "adb_command_ok": False,
    "online_device_count": 0,
    "configured_device_online": False,
    "failure_category": None,
}
try:
    config = load_zacks_device_config()
    login = config["login_info"]
    probe["configuration_valid"] = True
    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
        output, _, exit_status = exec_cmd_by_ssh_with_status(
            login["device_ip"],
            login["port"],
            login["username"],
            login["password"],
            login["host_key_sha256"],
            build_login_shell_adb_command("devices"),
        )
    probe["ssh_connected"] = exit_status is not None
    probe["adb_command_ok"] = exit_status == 0
    online_devices = []
    if exit_status == 0 and output is not None:
        for line in output.splitlines():
            parts = re.split(r"\s+", line.strip())
            if len(parts) >= 2 and parts[1] == "device":
                online_devices.append(parts[0])
    probe["online_device_count"] = len(online_devices)
    preferred = {config.get("adb_serial"), config.get("device_name")}
    probe["configured_device_online"] = any(
        serial in online_devices for serial in preferred if isinstance(serial, str)
    )
    if exit_status is None:
        probe["failure_category"] = "ssh_connection_failed"
    elif exit_status != 0:
        probe["failure_category"] = "adb_command_failed"
    elif not online_devices:
        probe["failure_category"] = "no_online_adb_devices"
    elif not probe["configured_device_online"]:
        probe["failure_category"] = "configured_device_not_online"
except ValueError:
    probe["failure_category"] = "configuration_invalid"
except Exception as exc:
    probe["failure_category"] = "probe_error"
    probe["error_type"] = type(exc).__name__

print(
    json.dumps(
        {
            "ok": True,
            "dag_id": DAG_ID,
            "latest_failed_run": run_row,
            "task_instances": task_rows,
            "error_evidence": evidence,
            "current_probe": probe,
            "read_only": True,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only diagnosis for the Zacks phone reboot DAG."
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
        raise OpsError(result.stderr.strip() or "phone diagnostic SSH command failed")
    payload = parse_remote_result(result.stdout)
    evidence = payload.get("error_evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if not isinstance(item, dict):
                continue
            signatures = item.get("error_signatures")
            if isinstance(signatures, list):
                item["error_signatures"] = [
                    redact_error(str(signature)) for signature in signatures
                ]
    emit(payload, args.format)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
