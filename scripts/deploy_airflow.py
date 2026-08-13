#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
from typing import Any

import yaml
from _ops import (
    REPO_ROOT,
    OpsError,
    airflow_remote,
    emit,
    run,
    ssh_command,
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


def local_preflight(target_commit: str) -> dict[str, Any]:
    status = run(["git", "status", "--porcelain"]).stdout.strip()
    run(["git", "fetch", "--quiet", "origin", "main"])
    pushed = (
        run(
            ["git", "merge-base", "--is-ancestor", target_commit, "origin/main"],
            check=False,
        ).returncode
        == 0
    )
    checks = {
        "clean_worktree": not status,
        "target_commit_is_pushed": pushed,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
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
target_dag_ids_b64="$5"
airflow_version="$6"
secret_dir="$7"
base_url="$8"
execution_api_url="$9"
recover_active_tasks="${{10}}"
cd "$repo_path"

current_commit="$(git rev-parse HEAD)"
current_image="wechat-on-airflow:${{airflow_version}}-$(printf '%s' "$current_commit" | cut -c1-7)"
active_image="$current_image"

validate_runtime_secrets() {{
    test "$(stat -c '%a:%u:%g' "$secret_dir")" = "750:0:0"
    for filename in \
        airflow_fernet_key \
        airflow_api_secret_key \
        airflow_jwt_secret \
        airflow_database_password \
        airflow_admin_password; do
        test -s "$secret_dir/$filename"
        test "$(stat -c '%a:%u:%g' "$secret_dir/$filename")" = "640:0:0"
    done
}}

compose() {{
    if docker compose version >/dev/null 2>&1; then
        AIRFLOW_IMAGE_NAME="$active_image" \
        AIRFLOW_BASE_URL="$base_url" \
        AIRFLOW_EXECUTION_API_SERVER_URL="$execution_api_url" \
        AIRFLOW_SECRET_DIR="$secret_dir" \
        docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        AIRFLOW_IMAGE_NAME="$active_image" \
        AIRFLOW_BASE_URL="$base_url" \
        AIRFLOW_EXECUTION_API_SERVER_URL="$execution_api_url" \
        AIRFLOW_SECRET_DIR="$secret_dir" \
        docker-compose "$@"
    else
        printf 'docker compose is unavailable\\n' >&2
        return 127
    fi
}}

test -z "$(git status --porcelain --untracked-files=no)"
validate_runtime_secrets
compose config --quiet </dev/null
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
git fetch --quiet origin </dev/null
git cat-file -e "$target_commit^{{commit}}"
git merge-base --is-ancestor "$target_commit" origin/main

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
dag_state_file=".deploy-dag-state-${{timestamp}}"

compose exec -T -e TARGET_DAG_IDS_B64="$target_dag_ids_b64" \
    "$api_service" python - >"$dag_state_file" <<'PY'
import base64
import json
import os

import yaml
from sqlalchemy import select
from airflow.models.dag import DagModel
from airflow.utils.session import create_session

with open("/opt/airflow/project/config/active-components.yaml", encoding="utf-8") as handle:
    current_dag_ids = [item["dag_id"] for item in yaml.safe_load(handle)["active_dags"]]
target_dag_ids = json.loads(base64.b64decode(os.environ["TARGET_DAG_IDS_B64"]))
all_dag_ids = sorted(set(current_dag_ids) | set(target_dag_ids))
with create_session() as session:
    states = dict(
        session.execute(
            select(DagModel.dag_id, DagModel.is_paused).where(DagModel.dag_id.in_(all_dag_ids))
        ).all()
    )
for dag_id in current_dag_ids:
    print(f"current\\t{{int(bool(states.get(dag_id, True)))}}\\t{{dag_id}}")
for dag_id in target_dag_ids:
    print(f"target\\t{{int(bool(states.get(dag_id, True)))}}\\t{{dag_id}}")
PY

pause_regex="$(python3 - "$dag_state_file" <<'PY'
import re
import sys
from pathlib import Path

dag_ids = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    scope, was_paused, dag_id = line.split("\\t", 2)
    if scope == "current" and was_paused == "0":
        dag_ids.append(re.escape(dag_id))
if dag_ids:
    print("^(?:" + "|".join(dag_ids) + ")$")
PY
)"

restore_regex="$(python3 - "$dag_state_file" <<'PY'
import re
import sys
from pathlib import Path

dag_ids = []
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    scope, was_paused, dag_id = line.split("\\t", 2)
    if scope == "target" and was_paused == "0":
        dag_ids.append(re.escape(dag_id))
if dag_ids:
    print("^(?:" + "|".join(dag_ids) + ")$")
PY
)"

retired_dag_count="$(python3 - "$dag_state_file" <<'PY'
import sys
from pathlib import Path

current = set()
target = set()
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    scope, _was_paused, dag_id = line.split("\\t", 2)
    (current if scope == "current" else target).add(dag_id)
print(len(current - target))
PY
)"

restore_dags() {{
    regex="$1"
    if [ -z "$regex" ]; then
        return 0
    fi
    restore_deadline="$(( $(date +%s) + 180 ))"
    while :; do
        restore_ok=true
        restore_service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{{print; exit}}')"
        if [ -z "$restore_service" ]; then
            restore_ok=false
        elif ! compose exec -T "$restore_service" airflow dags unpause \
            --treat-dag-id-as-regex --yes "$regex" </dev/null >/dev/null 2>&1; then
            restore_ok=false
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

execution_services_stopped=false

rollback() {{
    rc="${{1:-$?}}"
    trap - EXIT HUP INT TERM
    if [ "$rc" -ne 0 ] || [ "$execution_services_stopped" = "true" ]; then
        git checkout --quiet --detach "$current_commit" || true
        active_image="$current_image"
        compose up -d --no-deps {services} >/dev/null 2>&1 || true
        restore_dags "$pause_regex" || true
    fi
    rm -f "$dag_state_file"
    exit "$rc"
}}
trap rollback EXIT
trap 'rollback 129' HUP
trap 'rollback 130' INT
trap 'rollback 143' TERM

if [ -n "$pause_regex" ]; then
    compose exec -T "$api_service" airflow dags pause \
        --treat-dag-id-as-regex --yes "$pause_regex" </dev/null >/dev/null
fi

recovered_task_instances=0
recovered_dag_runs=0
purged_broker_keys=0
if [ "$recover_active_tasks" = "true" ]; then
    compose stop -t 15 airflow-scheduler airflow-worker airflow-triggerer </dev/null >/dev/null
    execution_services_stopped=true
    recovery_result="$(compose exec -T -e TARGET_DAG_IDS_B64="$target_dag_ids_b64" \
        "$api_service" python - <<'PY'
import base64
import json
import os
from datetime import UTC, datetime

from sqlalchemy import select
from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.utils.session import create_session

dag_ids = json.loads(base64.b64decode(os.environ.pop("TARGET_DAG_IDS_B64")))
active_task_states = ({active_task_states})
active_run_states = ("queued", "running")
now = datetime.now(UTC)

with create_session() as session:
    task_instances = list(
        session.scalars(
            select(TaskInstance).where(
                TaskInstance.dag_id.in_(dag_ids),
                TaskInstance.state.in_(active_task_states),
            )
        )
    )
    dag_runs = list(
        session.scalars(
            select(DagRun).where(
                DagRun.dag_id.in_(dag_ids), DagRun.state.in_(active_run_states)
            )
        )
    )
    for task_instance in task_instances:
        task_instance.state = "failed"
        task_instance.end_date = task_instance.end_date or now
        if task_instance.start_date is not None and task_instance.duration is None:
            task_instance.duration = max((now - task_instance.start_date).total_seconds(), 0)
    for dag_run in dag_runs:
        dag_run.state = "failed"
        dag_run.end_date = dag_run.end_date or now
    session.flush()
print(json.dumps({{"task_instances": len(task_instances), "dag_runs": len(dag_runs)}}))
PY
)"
    recovered_task_instances="$(RECOVERY_RESULT="$recovery_result" python3 - <<'PY'
import json
import os

print(json.loads(os.environ.pop("RECOVERY_RESULT").splitlines()[-1])["task_instances"])
PY
)"
    recovered_dag_runs="$(RECOVERY_RESULT="$recovery_result" python3 - <<'PY'
import json
import os

print(json.loads(os.environ.pop("RECOVERY_RESULT").splitlines()[-1])["dag_runs"])
PY
)"
    purged_broker_keys="$(compose exec -T redis redis-cli DBSIZE </dev/null | tr -d '\r')"
    test "$(compose exec -T redis redis-cli FLUSHDB </dev/null | tr -d '\r')" = "OK"
fi

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
active_image="$target_image"

compose config --quiet </dev/null
compose build --quiet airflow-api-server </dev/null >/dev/null
docker image inspect "$target_image" >/dev/null
compose up -d --no-deps {services} </dev/null >/dev/null
execution_services_stopped=false

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
restore_dags "$restore_regex"
rm -f "$dag_state_file"
trap - EXIT HUP INT TERM
python3 - "$current_commit" "$target_commit" "$target_image" "$container_count" "$current_image" "$initial_active_tasks" "$retired_dag_count" "$recovered_task_instances" "$recovered_dag_runs" "$purged_broker_keys" <<'PY'
import json
import sys

print(json.dumps({{
    "ok": True,
    "applied": True,
    "previous_commit": sys.argv[1],
    "current_commit": sys.argv[2],
    "target_image": sys.argv[3],
    "healthy_application_containers": int(sys.argv[4]),
    "rollback_image": sys.argv[5],
    "drained_task_instances": int(sys.argv[6]),
    "retired_dags_left_paused": int(sys.argv[7]),
    "recovered_task_instances": int(sys.argv[8]),
    "recovered_dag_runs": int(sys.argv[9]),
    "purged_broker_keys": int(sys.argv[10]),
    "outbox_preserved": True,
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
    parser.add_argument("--recover-active-tasks", action="store_true")
    parser.add_argument("--target-commit", default="HEAD")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    target_commit = resolve_target_commit(args.target_commit)
    target_manifest = yaml.safe_load(
        run(["git", "show", f"{target_commit}:config/active-components.yaml"]).stdout
    )
    target_dag_ids = [str(item["dag_id"]) for item in target_manifest["active_dags"]]
    target_dag_ids_b64 = base64.b64encode(
        json.dumps(target_dag_ids, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    runtime_target = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    target_image = airflow_image_name(str(runtime_target["target"]["airflow"]), target_commit)
    preflight = local_preflight(target_commit)
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

    remote = airflow_remote()
    command = [
        *ssh_command(remote),
        "bash",
        "-s",
        "--",
        remote["repository_path"],
        target_commit,
        target_image,
        "apply" if args.apply else "dry-run",
        target_dag_ids_b64,
        str(runtime_target["target"]["airflow"]),
        str(runtime_target["target"]["production_secret_directory"]),
        str(runtime_target["managed_services"]["cloudflare_tunnel"]["public_base_url"]),
        str(runtime_target["target"]["execution_api_server_url"]),
        "true" if args.recover_active_tasks else "false",
    ]
    result = run(command, check=False, input_text=remote_script())
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
