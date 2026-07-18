#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml
from _ops import (
    REPO_ROOT,
    OpsError,
    emit,
    latest_successful_backup,
    merged_env,
    required_env,
    run,
)

APPLICATION_SERVICES = (
    "airflow-api-server",
    "airflow-scheduler",
    "airflow-dag-processor",
    "airflow-worker",
    "airflow-triggerer",
)
ACTIVE_TASK_STATES = (
    "running",
    "queued",
    "scheduled",
    "restarting",
    "up_for_retry",
    "up_for_reschedule",
)
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def airflow_image_name(airflow_version: str, commit: str) -> str:
    if not COMMIT_PATTERN.fullmatch(commit):
        raise OpsError("target commit must resolve to a full SHA-1")
    return f"wechat-on-airflow:{airflow_version}-{commit[:7]}"


def resolve_target_commit(revision: str) -> str:
    result = run(["git", "rev-parse", "--verify", f"{revision}^{{commit}}"])
    commit = result.stdout.strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise OpsError("target revision did not resolve to a full commit")
    return commit


def local_preflight(target_commit: str, backup_dir: Path) -> dict[str, Any]:
    status = run(["git", "status", "--porcelain"]).stdout.strip()
    upstream_result = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        check=False,
    )
    upstream = upstream_result.stdout.strip() if upstream_result.returncode == 0 else ""
    pushed = bool(upstream) and (
        run(
            ["git", "merge-base", "--is-ancestor", target_commit, upstream],
            check=False,
        ).returncode
        == 0
    )
    backup = latest_successful_backup(backup_dir)
    checks = {
        "clean_worktree": not status,
        "has_upstream": bool(upstream),
        "target_commit_is_pushed": pushed,
        "encrypted_database_backup": backup is not None,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "backup_file": str(backup) if backup else None,
    }


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
    raise OpsError("remote deployment did not return a structured result")


def remote_script() -> str:
    services = " ".join(APPLICATION_SERVICES)
    active_task_states = ", ".join(repr(state) for state in ACTIVE_TASK_STATES)
    return f"""\
set -eu
repo_path="$1"
target_commit="$2"
target_image="$3"
mode="$4"
cd "$repo_path"

compose() {{
    if docker compose version >/dev/null 2>&1; then
        docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose "$@"
    else
        printf 'docker compose is unavailable\\n' >&2
        return 127
    fi
}}

current_commit="$(git rev-parse HEAD)"
test -z "$(git status --porcelain --untracked-files=no)"
compose config --quiet
api_service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{{print; exit}}')"
test -n "$api_service"

active_task_count() {{
    compose exec -T "$api_service" python - <<'PY'
import yaml
from sqlalchemy import func, select
from airflow.models.taskinstance import TaskInstance
from airflow.utils.session import create_session

with open("/opt/airflow/project/config/active-components.yaml", encoding="utf-8") as handle:
    dag_ids = [item["dag_id"] for item in yaml.safe_load(handle)["active_dags"]]
with create_session() as session:
    count = session.scalar(
        select(func.count())
        .select_from(TaskInstance)
        .where(
            TaskInstance.dag_id.in_(dag_ids),
            TaskInstance.state.in_([{active_task_states}]),
        )
    )
print(int(count or 0))
PY
}}

if [ "$mode" = "dry-run" ]; then
    target_available=false
    if git cat-file -e "$target_commit^{{commit}}" 2>/dev/null; then
        target_available=true
    fi
    active_tasks="$(active_task_count)"
    python3 - "$current_commit" "$target_commit" "$target_image" "$target_available" "$active_tasks" <<'PY'
import json
import sys

print(json.dumps({{
    "ok": True,
    "applied": False,
    "current_commit": sys.argv[1],
    "target_commit": sys.argv[2],
    "target_image": sys.argv[3],
    "target_already_available": sys.argv[4] == "true",
    "active_task_instances": int(sys.argv[5]),
}}, sort_keys=True))
PY
    exit 0
fi

test "$mode" = "apply"
git fetch --quiet origin
git cat-file -e "$target_commit^{{commit}}"
git merge-base --is-ancestor "$target_commit" origin/main

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
env_backup=".env.deploy-backup-${{timestamp}}-${{current_commit}}"
dag_state_file=".deploy-dag-state-${{timestamp}}"
cp -p .env "$env_backup"
chmod 600 "$env_backup"

compose exec -T "$api_service" python - >"$dag_state_file" <<'PY'
import yaml
from sqlalchemy import select
from airflow.models.dag import DagModel
from airflow.utils.session import create_session

with open("/opt/airflow/project/config/active-components.yaml", encoding="utf-8") as handle:
    dag_ids = [item["dag_id"] for item in yaml.safe_load(handle)["active_dags"]]
with create_session() as session:
    states = dict(
        session.execute(
            select(DagModel.dag_id, DagModel.is_paused).where(DagModel.dag_id.in_(dag_ids))
        ).all()
    )
for dag_id in dag_ids:
    print(f"{{int(bool(states.get(dag_id, True)))}}\\t{{dag_id}}")
PY

restore_dags() {{
    restore_deadline="$(( $(date +%s) + 180 ))"
    while :; do
        restore_ok=true
        restore_service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{{print; exit}}')"
        if [ -z "$restore_service" ]; then
            restore_ok=false
        else
            while IFS=$'\\t' read -r was_paused dag_id; do
                if [ "$was_paused" = "0" ] && ! compose exec -T "$restore_service" airflow dags unpause "$dag_id" >/dev/null 2>&1; then
                    restore_ok=false
                fi
            done <"$dag_state_file"
        fi
        if [ "$restore_ok" = "true" ]; then
            return 0
        fi
        if [ "$(date +%s)" -ge "$restore_deadline" ]; then
            return 1
        fi
        sleep 5
    done
}}

rollback() {{
    rc="$?"
    trap - EXIT INT TERM
    if [ "$rc" -ne 0 ]; then
        git checkout --quiet --detach "$current_commit" || true
        cp -p "$env_backup" .env || true
        compose up -d --no-deps {services} >/dev/null 2>&1 || true
        restore_dags || true
    fi
    rm -f "$dag_state_file"
    exit "$rc"
}}
trap rollback EXIT INT TERM

while IFS=$'\\t' read -r was_paused dag_id; do
    if [ "$was_paused" = "0" ]; then
        compose exec -T "$api_service" airflow dags pause "$dag_id" >/dev/null
    fi
done <"$dag_state_file"

drain_deadline="$(( $(date +%s) + 600 ))"
initial_active_tasks="$(active_task_count)"
while [ "$(active_task_count)" -ne 0 ]; do
    if [ "$(date +%s)" -ge "$drain_deadline" ]; then
        printf 'active task instances did not drain before timeout\\n' >&2
        exit 1
    fi
    sleep 5
done

git checkout --quiet --detach "$target_commit"
python3 - .env "$target_image" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
image = sys.argv[2]
lines = path.read_text(encoding="utf-8").splitlines()
replacement = f"AIRFLOW_IMAGE_NAME={{image}}"
updated = []
found = False
for line in lines:
    if line.startswith("AIRFLOW_IMAGE_NAME="):
        updated.append(replacement)
        found = True
    else:
        updated.append(line)
if not found:
    updated.append(replacement)
path.write_text("\\n".join(updated) + "\\n", encoding="utf-8")
PY
chmod 600 .env

compose config --quiet
compose build --quiet airflow-api-server >/dev/null
docker image inspect "$target_image" >/dev/null
compose up -d --no-deps {services} >/dev/null

deadline="$(( $(date +%s) + 300 ))"
while :; do
    all_healthy=true
    container_count=0
    for service in {services}; do
        ids="$(compose ps -q "$service")"
        if [ -z "$ids" ]; then
            all_healthy=false
            continue
        fi
        for container_id in $ids; do
            container_count="$((container_count + 1))"
            state="$(docker inspect --format '{{{{.State.Status}}}}' "$container_id")"
            health="$(docker inspect --format '{{{{if .State.Health}}}}{{{{.State.Health.Status}}}}{{{{else}}}}none{{{{end}}}}' "$container_id")"
            if [ "$state" != "running" ] || {{ [ "$health" != "healthy" ] && [ "$health" != "none" ]; }}; then
                all_healthy=false
            fi
        done
    done
    if [ "$all_healthy" = "true" ]; then
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        printf 'application services did not become healthy before timeout\\n' >&2
        exit 1
    fi
    sleep 5
done

api_service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{{print; exit}}')"
test -n "$api_service"
restore_dags
rm -f "$dag_state_file"
trap - EXIT INT TERM
python3 - "$current_commit" "$target_commit" "$target_image" "$container_count" "$env_backup" "$initial_active_tasks" <<'PY'
import json
import sys

print(json.dumps({{
    "ok": True,
    "applied": True,
    "previous_commit": sys.argv[1],
    "current_commit": sys.argv[2],
    "target_image": sys.argv[3],
    "healthy_application_containers": int(sys.argv[4]),
    "rollback_env_file": sys.argv[5],
    "drained_task_instances": int(sys.argv[6]),
    "dag_pause_state_restored": True,
}}, sort_keys=True))
PY
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy one exact pushed Airflow application commit."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--target-commit", default="HEAD")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path.home() / "airflow-production-backups",
    )
    args = parser.parse_args()

    target_commit = resolve_target_commit(args.target_commit)
    runtime_target = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    target_image = airflow_image_name(str(runtime_target["target"]["airflow"]), target_commit)
    preflight = local_preflight(target_commit, args.backup_dir)
    if not preflight["ok"]:
        emit(
            {
                "ok": False,
                "mode": "apply" if args.apply else "dry-run",
                "target_commit": target_commit,
                "target_image": target_image,
                "preflight": preflight,
            },
            args.format,
        )
        raise SystemExit(1)

    values = merged_env()
    remote = required_env(values, ["SERVER_IP", "PORT", "USERNAME", "PASSWORD", "REMOTE_PATH"])
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
        target_commit,
        target_image,
        "apply" if args.apply else "dry-run",
    ]
    result = run(command, env=ssh_env, check=False, input_text=remote_script())
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else "remote deployment command failed"
        raise OpsError(message)

    payload = {
        "ok": True,
        "mode": "apply" if args.apply else "dry-run",
        "target_commit": target_commit,
        "target_image": target_image,
        "preflight": preflight,
        "remote": parse_remote_result(result.stdout),
    }
    emit(payload, args.format)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"deploy-airflow: {exc}")
        raise SystemExit(1) from exc
