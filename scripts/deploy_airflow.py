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
cd "$repo_path"

current_commit="$(git rev-parse HEAD)"
current_image="wechat-on-airflow:${{airflow_version}}-$(printf '%s' "$current_commit" | cut -c1-7)"
active_image="$current_image"

secret_value() {{
    filename="$1"
    legacy_name="$2"
    if [ -s "$secret_dir/$filename" ]; then
        cat "$secret_dir/$filename"
        return
    fi
    python3 - "$repo_path/.env" "$legacy_name" <<'PY'
import shlex
import sys
from pathlib import Path

path = Path(sys.argv[1])
name = sys.argv[2]
if not path.is_file():
    raise SystemExit(1)
for raw_line in path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    if key.strip() != name:
        continue
    value = value.strip()
    if value and value[0] in {{"'", '"'}}:
        parsed = shlex.split(value)
        value = parsed[0] if parsed else ""
    if not value:
        raise SystemExit(1)
    print(value)
    raise SystemExit(0)
raise SystemExit(1)
PY
}}

compose() {{
    airflow_fernet_key="$(secret_value airflow_fernet_key AIRFLOW_FERNET_KEY)"
    airflow_api_secret_key="$(secret_value airflow_api_secret_key AIRFLOW_API_SECRET_KEY)"
    airflow_jwt_secret="$(secret_value airflow_jwt_secret AIRFLOW_JWT_SECRET)"
    airflow_database_password="$(secret_value airflow_database_password AIRFLOW_DATABASE_PASSWORD)"
    airflow_admin_password="$(secret_value airflow_admin_password AIRFLOW_PASSWORD)"
    if docker compose version >/dev/null 2>&1; then
        AIRFLOW_IMAGE_NAME="$active_image" \
        AIRFLOW_BASE_URL="$base_url" \
        AIRFLOW_EXECUTION_API_SERVER_URL="$execution_api_url" \
        AIRFLOW_SECRET_DIR="$secret_dir" \
        AIRFLOW_FERNET_KEY="$airflow_fernet_key" \
        AIRFLOW_API_SECRET_KEY="$airflow_api_secret_key" \
        AIRFLOW_JWT_SECRET="$airflow_jwt_secret" \
        AIRFLOW_DATABASE_PASSWORD="$airflow_database_password" \
        AIRFLOW_PASSWORD="$airflow_admin_password" \
        docker compose "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        AIRFLOW_IMAGE_NAME="$active_image" \
        AIRFLOW_BASE_URL="$base_url" \
        AIRFLOW_EXECUTION_API_SERVER_URL="$execution_api_url" \
        AIRFLOW_SECRET_DIR="$secret_dir" \
        AIRFLOW_FERNET_KEY="$airflow_fernet_key" \
        AIRFLOW_API_SECRET_KEY="$airflow_api_secret_key" \
        AIRFLOW_JWT_SECRET="$airflow_jwt_secret" \
        AIRFLOW_DATABASE_PASSWORD="$airflow_database_password" \
        AIRFLOW_PASSWORD="$airflow_admin_password" \
        docker-compose "$@"
    else
        printf 'docker compose is unavailable\\n' >&2
        return 127
    fi
}}

test -z "$(git status --porcelain --untracked-files=no)"
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

rollback() {{
    rc="${{1:-$?}}"
    trap - EXIT HUP INT TERM
    if [ "$rc" -ne 0 ]; then
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

drain_deadline="$(( $(date +%s) + 600 ))"
initial_active_tasks="$(active_task_count)"
while [ "$(active_task_count)" -ne 0 ]; do
    if [ "$(date +%s)" -ge "$drain_deadline" ]; then
        printf 'active task instances did not drain before timeout\\n' >&2
        exit 1
    fi
    sleep 5
done

migrate_runtime_secrets() {{
    python3 - "$repo_path/.env" "$secret_dir" <<'PY'
import os
import shlex
import sys
from pathlib import Path

legacy_path = Path(sys.argv[1])
secret_dir = Path(sys.argv[2])
mapping = {{
    "AIRFLOW_FERNET_KEY": "airflow_fernet_key",
    "AIRFLOW_API_SECRET_KEY": "airflow_api_secret_key",
    "AIRFLOW_JWT_SECRET": "airflow_jwt_secret",
    "AIRFLOW_DATABASE_PASSWORD": "airflow_database_password",
    "AIRFLOW_PASSWORD": "airflow_admin_password",
}}
values = {{}}
if legacy_path.is_file():
    for raw_line in legacy_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] in {{"'", '"'}}:
            parsed = shlex.split(value)
            value = parsed[0] if parsed else ""
        values[key] = value

secret_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
secret_dir.chmod(0o750)
for legacy_name, filename in mapping.items():
    destination = secret_dir / filename
    if destination.is_file() and destination.stat().st_size:
        destination.chmod(0o640)
        continue
    value = values.get(legacy_name, "")
    if not value:
        raise SystemExit(f"missing runtime secret: {{legacy_name}}")
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(value)
        handle.write("\\n")
PY
}}

migrate_runtime_secrets
git checkout --quiet --detach "$target_commit"
active_image="$target_image"

compose config --quiet </dev/null
compose build --quiet airflow-api-server </dev/null >/dev/null
docker image inspect "$target_image" >/dev/null
compose up -d --no-deps {services} </dev/null >/dev/null

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
for legacy_env in .env .env.deploy-backup-*; do
    if [ -f "$legacy_env" ]; then
        if command -v shred >/dev/null 2>&1; then
            shred --remove --zero "$legacy_env"
        else
            rm -f "$legacy_env"
        fi
    fi
done
trap - EXIT HUP INT TERM
python3 - "$current_commit" "$target_commit" "$target_image" "$container_count" "$current_image" "$initial_active_tasks" "$retired_dag_count" <<'PY'
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
