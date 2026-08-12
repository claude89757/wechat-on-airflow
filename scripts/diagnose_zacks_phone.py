#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
from pathlib import Path

from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.utils.session import create_session

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
log_root = Path("/opt/airflow/logs") / f"dag_id={DAG_ID}" / f"run_id={run.run_id}"
for task in task_rows:
    if task["state"].lower() != "failed":
        continue
    task_root = log_root / f"task_id={task['task_id']}"
    paths = sorted(
        task_root.rglob("attempt=*.log") if task_root.is_dir() else [],
        key=lambda path: path.stat().st_mtime,
    )
    signatures = []
    for path in paths[-3:]:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines[-400:]:
            if SIGNAL.search(line):
                sanitized = sanitize(line)
                if sanitized not in signatures:
                    signatures.append(sanitized)
    evidence.append(
        {
            "task_id": task["task_id"],
            "log_files_found": len(paths),
            "error_signatures": signatures[-40:],
        }
    )

print(
    json.dumps(
        {
            "ok": True,
            "dag_id": DAG_ID,
            "latest_failed_run": {
                "run_id": run.run_id,
                "state": str(run.state),
                "logical_date": timestamp(run.logical_date),
                "started_at": timestamp(run.start_date),
                "ended_at": timestamp(run.end_date),
            },
            "task_instances": task_rows,
            "error_evidence": evidence,
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
    emit(payload, args.format)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
