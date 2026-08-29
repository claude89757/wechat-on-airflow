#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import re
from typing import Any

from _ops import OpsError, airflow_remote, emit, run, ssh_command

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
WECHAT_DAG_IDS = (
    "深圳湾网球场巡检",
    "大湾区网球场巡检",
    "深圳金地网球场巡检",
    "上越沙河网球场巡检",
    "TOPS科技园网球场巡检",
    "泛思博特福中福网球场巡检",
    "深圳市体育中心网球场巡检",
    "大沙河国际网球中心巡检",
)


def parse_remote_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise OpsError("WeChat delivery quiesce returned no structured result")


def is_quiesced(verification: dict[str, Any]) -> bool:
    return (
        verification.get("paused_wechat_dags") == len(WECHAT_DAG_IDS)
        and verification.get("active_wechat_task_instances") == 0
        and verification.get("active_wechat_dag_runs") == 0
    )


def remote_script() -> str:
    return r"""
set -eu
repo_path="$1"
operation_commit="$2"
wechat_dag_ids_b64="$3"
cd "$repo_path"

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

current_commit="$(git rev-parse HEAD)"
api_service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
test -n "$api_service"

restart_services() {
    compose up -d --no-deps airflow-worker airflow-scheduler airflow-triggerer >/dev/null 2>&1 || true
}
trap restart_services EXIT HUP INT TERM

# Freeze task production and execution before changing metadata or the broker.
compose stop -t 15 airflow-scheduler airflow-worker airflow-triggerer >/dev/null

state_result="$(compose exec -T -e WECHAT_DAG_IDS_B64="$wechat_dag_ids_b64" \
    "$api_service" python - <<'PY'
import base64
import json
import os
from datetime import UTC, datetime

from sqlalchemy import select

from airflow.models.dag import DagModel
from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.utils.session import create_session

wechat_dag_ids = json.loads(base64.b64decode(os.environ.pop("WECHAT_DAG_IDS_B64")))
active_task_states = (
    "running",
    "queued",
    "scheduled",
    "restarting",
    "up_for_retry",
    "up_for_reschedule",
    "deferred",
)
active_run_states = ("queued", "running")
now = datetime.now(UTC)

with create_session() as session:
    dag_models = list(
        session.scalars(select(DagModel).where(DagModel.dag_id.in_(wechat_dag_ids)))
    )
    found_dag_ids = {model.dag_id for model in dag_models}
    missing_dag_ids = sorted(set(wechat_dag_ids) - found_dag_ids)
    if missing_dag_ids:
        raise RuntimeError(f"managed WeChat DAGs are missing: {len(missing_dag_ids)}")
    for model in dag_models:
        model.is_paused = True

    task_instances = list(
        session.scalars(select(TaskInstance).where(TaskInstance.state.in_(active_task_states)))
    )
    active_runs = list(session.scalars(select(DagRun).where(DagRun.state.in_(active_run_states))))

    for task_instance in task_instances:
        task_instance.state = "failed"
        if task_instance.end_date is None:
            task_instance.end_date = now
        if task_instance.start_date is not None and task_instance.duration is None:
            task_instance.duration = max((now - task_instance.start_date).total_seconds(), 0)

    for dag_run in active_runs:
        dag_run.state = "failed"
        if dag_run.end_date is None:
            dag_run.end_date = now

    session.flush()
    print(
        json.dumps(
            {
                "paused_wechat_dags": len(dag_models),
                "cleared_task_instances": len(task_instances),
                "cleared_dag_runs": len(active_runs),
            },
            sort_keys=True,
        )
    )
PY
)"

# Redis database 0 is dedicated to the Celery broker. Flush it so reserved
# messages cannot reappear after the broker visibility timeout.
purged_broker_keys="$(compose exec -T redis redis-cli DBSIZE | tr -d '\r')"
test "$(compose exec -T redis redis-cli FLUSHDB | tr -d '\r')" = "OK"

restart_services
trap - EXIT HUP INT TERM

deadline="$(( $(date +%s) + 180 ))"
while :; do
    services_healthy=true
    for service in airflow-scheduler airflow-worker airflow-triggerer; do
        service_ids="$(compose ps -q "$service")"
        if [ -z "$service_ids" ]; then
            services_healthy=false
            continue
        fi
        for service_id in $service_ids; do
            state="$(docker inspect --format '{{.State.Status}}' "$service_id")"
            health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$service_id")"
            if [ "$state" != "running" ] || { [ "$health" != "healthy" ] && [ "$health" != "none" ]; }; then
                services_healthy=false
            fi
        done
    done
    if [ "$services_healthy" = "true" ]; then
        break
    fi
    if [ "$(date +%s)" -ge "$deadline" ]; then
        printf 'Airflow scheduler or worker did not restart\n' >&2
        exit 1
    fi
    sleep 5
done

verification="$(compose exec -T -e WECHAT_DAG_IDS_B64="$wechat_dag_ids_b64" \
    "$api_service" python - <<'PY'
import base64
import json
import os

from sqlalchemy import func, select

from airflow.models.dag import DagModel
from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.utils.session import create_session

wechat_dag_ids = json.loads(base64.b64decode(os.environ.pop("WECHAT_DAG_IDS_B64")))
active_task_states = (
    "running",
    "queued",
    "scheduled",
    "restarting",
    "up_for_retry",
    "up_for_reschedule",
    "deferred",
)
active_run_states = ("queued", "running")

with create_session() as session:
    paused_count = session.scalar(
        select(func.count())
        .select_from(DagModel)
        .where(DagModel.dag_id.in_(wechat_dag_ids), DagModel.is_paused.is_(True))
    )
    active_task_count = session.scalar(
        select(func.count())
        .select_from(TaskInstance)
        .where(
            TaskInstance.dag_id.in_(wechat_dag_ids),
            TaskInstance.state.in_(active_task_states),
        )
    )
    active_run_count = session.scalar(
        select(func.count())
        .select_from(DagRun)
        .where(DagRun.dag_id.in_(wechat_dag_ids), DagRun.state.in_(active_run_states))
    )

print(
    json.dumps(
        {
            "paused_wechat_dags": int(paused_count or 0),
            "active_wechat_task_instances": int(active_task_count or 0),
            "active_wechat_dag_runs": int(active_run_count or 0),
        },
        sort_keys=True,
    )
)
PY
)"

STATE_RESULT="$state_result" VERIFICATION="$verification" python3 - \
    "$current_commit" "$operation_commit" "$purged_broker_keys" <<'PY'
import json
import os
import sys

state = json.loads(os.environ.pop("STATE_RESULT"))
verification = json.loads(os.environ.pop("VERIFICATION"))
expected_paused = 8
ok = (
    verification.get("paused_wechat_dags") == expected_paused
    and verification.get("active_wechat_task_instances") == 0
    and verification.get("active_wechat_dag_runs") == 0
)
print(
    json.dumps(
        {
            "ok": ok,
            "applied": True,
            "runtime_commit": sys.argv[1],
            "operation_commit": sys.argv[2],
            "paused_wechat_dags": state["paused_wechat_dags"],
            "cleared_task_instances": state["cleared_task_instances"],
            "cleared_dag_runs": state["cleared_dag_runs"],
            "purged_broker_keys": int(sys.argv[3]),
            "outbox_preserved": True,
            "verification": verification,
        },
        sort_keys=True,
    )
)
if not ok:
    raise SystemExit(1)
PY
"""


def verification_script() -> str:
    return r"""
set -eu
cd "$1"
wechat_dag_ids_b64="$2"

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
compose exec -T -e WECHAT_DAG_IDS_B64="$wechat_dag_ids_b64" "$api_service" python - <<'PY'
import base64
import json
import os

from sqlalchemy import func, select

from airflow.models.dag import DagModel
from airflow.models.dagrun import DagRun
from airflow.models.taskinstance import TaskInstance
from airflow.utils.session import create_session

wechat_dag_ids = json.loads(base64.b64decode(os.environ.pop("WECHAT_DAG_IDS_B64")))
active_task_states = (
    "running",
    "queued",
    "scheduled",
    "restarting",
    "up_for_retry",
    "up_for_reschedule",
    "deferred",
)
active_run_states = ("queued", "running")

with create_session() as session:
    paused_count = session.scalar(
        select(func.count())
        .select_from(DagModel)
        .where(DagModel.dag_id.in_(wechat_dag_ids), DagModel.is_paused.is_(True))
    )
    active_task_count = session.scalar(
        select(func.count())
        .select_from(TaskInstance)
        .where(
            TaskInstance.dag_id.in_(wechat_dag_ids),
            TaskInstance.state.in_(active_task_states),
        )
    )
    active_run_count = session.scalar(
        select(func.count())
        .select_from(DagRun)
        .where(DagRun.dag_id.in_(wechat_dag_ids), DagRun.state.in_(active_run_states))
    )

print(
    json.dumps(
        {
            "paused_wechat_dags": int(paused_count or 0),
            "active_wechat_task_instances": int(active_task_count or 0),
            "active_wechat_dag_runs": int(active_run_count or 0),
        },
        sort_keys=True,
    )
)
PY
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pause WeChat-producing DAGs and clear current Airflow work."
    )
    parser.add_argument("--target-commit", default="HEAD")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    target_commit = run(
        ["git", "rev-parse", "--verify", f"{args.target_commit}^{{commit}}"]
    ).stdout.strip()
    if not COMMIT_PATTERN.fullmatch(target_commit):
        raise OpsError("target revision did not resolve to a full commit")
    run(["git", "fetch", "--quiet", "origin", "main"])
    if (
        run(
            ["git", "merge-base", "--is-ancestor", target_commit, "origin/main"],
            check=False,
        ).returncode
        != 0
    ):
        raise OpsError("target commit is not on origin/main")

    dag_ids_b64 = base64.b64encode(
        json.dumps(WECHAT_DAG_IDS, ensure_ascii=False).encode("utf-8")
    ).decode("ascii")
    remote = airflow_remote()

    verification_command = [
        *ssh_command(remote),
        "bash",
        "-s",
        "--",
        remote["repository_path"],
        dag_ids_b64,
    ]
    initial_verification_result = run(
        verification_command,
        check=False,
        input_text=verification_script(),
    )
    if initial_verification_result.returncode == 0:
        initial_verification = parse_remote_result(initial_verification_result.stdout)
        if is_quiesced(initial_verification):
            emit(
                {
                    "ok": True,
                    "applied": False,
                    "already_quiesced": True,
                    "operation_commit": target_commit,
                    "outbox_preserved": True,
                    "verification": initial_verification,
                },
                args.format,
            )
            return

    action_result = run(
        [
            *ssh_command(remote),
            "bash",
            "-s",
            "--",
            remote["repository_path"],
            target_commit,
            dag_ids_b64,
        ],
        check=False,
        input_text=remote_script(),
    )
    if action_result.returncode:
        detail = action_result.stderr.strip().splitlines()
        raise OpsError(detail[-1] if detail else "WeChat delivery quiesce failed")

    verification_result = run(
        verification_command,
        check=False,
        input_text=verification_script(),
    )
    if verification_result.returncode:
        detail = verification_result.stderr.strip().splitlines()
        raise OpsError(detail[-1] if detail else "WeChat delivery verification failed")
    verification = parse_remote_result(verification_result.stdout)
    action_payload = None
    if action_result.stdout.strip():
        action_payload = parse_remote_result(action_result.stdout)
    ok = is_quiesced(verification)
    payload = {
        "ok": ok,
        "applied": True,
        "operation_commit": target_commit,
        "action_reported": action_payload is not None,
        "action": action_payload,
        "outbox_preserved": True,
        "verification": verification,
    }
    emit(payload, args.format)
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"quiesce-wechat-delivery: {exc}")
        raise SystemExit(1) from exc
