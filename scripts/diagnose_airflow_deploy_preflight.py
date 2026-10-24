#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, airflow_remote, emit, run, ssh_command

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

BUSINESS_BASELINE_PROBE = r"""
import json
import os
import re

report = {"ok": False, "read_only": True, "purpose": "baseline_only_not_release_acceptance"}
try:
    from sqlalchemy import text
    from wechat_airflow.host_core.database import get_engine

    with get_engine().connect() as connection:
        with connection.begin():
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '5s'"))
            connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            retired = connection.execute(text(
                "SELECT healthy, last_seen_at, last_seen_at > now() - interval '10 minutes' AS fresh "
                "FROM zacks.observation_state WHERE observation_key = 'szw:check_and_notify_day_3'"
            )).mappings().first()
            scopes = dict(connection.execute(text(
                "SELECT count(*) AS total_count, "
                "count(*) FILTER (WHERE healthy) AS healthy_count, "
                "count(*) FILTER (WHERE last_seen_at > now() - interval '10 minutes') AS fresh_count, "
                "count(*) FILTER (WHERE healthy AND last_seen_at > now() - interval '10 minutes') AS healthy_and_fresh_count "
                "FROM zacks.observation_state WHERE observation_key <> 'szw:check_and_notify_day_3'"
            )).mappings().one())
            delivery = dict(connection.execute(text(
                "SELECT (SELECT count(DISTINCT message_id) FROM zacks.notification_outbox "
                "WHERE status = 'delivered' AND submitted_at >= now() - interval '24 hours') AS email_delivered, "
                "(SELECT count(*) FROM zacks.wechat_outbox "
                "WHERE sent_at >= now() - interval '24 hours') AS wechat_sent"
            )).mappings().one())
            control = connection.execute(text(
                "SELECT deployment_commit, delivery_enabled, wechat_enabled, "
                "activated_at IS NOT NULL AS activated, now() AS observed_at FROM zacks.runtime_control WHERE singleton = true"
            )).mappings().one()
    commit = control["deployment_commit"]
    runtime_commit = os.environ.get("DEPLOYMENT_COMMIT", "")
    report.update({
        "ok": True,
        "observed_at": control["observed_at"].isoformat(),
        "freshness_minutes": 10,
        "window_hours": 24,
        "email_window_basis": "submitted_at",
        "wechat_window_basis": "sent_at",
        "retired_scope": {
            "observation_key": "szw:check_and_notify_day_3",
            "present": retired is not None,
            "healthy": retired["healthy"] is True if retired is not None else None,
            "fresh": retired["fresh"] is True if retired is not None else None,
            "last_seen_at": retired["last_seen_at"].isoformat() if retired is not None else None,
        },
        "non_retired_stored_scopes": scopes,
        "scope_filter": "excludes_only_known_retired_szw_day_3",
        "natural_delivery_last24h": delivery,
        "runtime": {
            "container_commit": runtime_commit if re.fullmatch(r"[0-9a-f]{40}", str(runtime_commit)) else None,
            "control_commit": commit if re.fullmatch(r"[0-9a-f]{40}", str(commit)) else None,
            "delivery_enabled": control["delivery_enabled"] is True,
            "wechat_enabled": control["wechat_enabled"] is True,
            "activated": control["activated"] is True,
        },
    })
except Exception:
    report = {"ok": False, "read_only": True, "failure_category": "business_baseline_query_failed"}
print(json.dumps(report, sort_keys=True))
"""


def resolve_target_commit(revision: str) -> str:
    result = run(["git", "rev-parse", "--verify", f"{revision}^{{commit}}"])
    commit = result.stdout.strip()
    if not COMMIT_PATTERN.fullmatch(commit):
        raise OpsError("target revision did not resolve to a full commit")
    return commit


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
    raise OpsError("Airflow preflight diagnosis did not return a structured result")


def remote_script() -> str:
    script = r"""\
set -u
repo_path="$1"
target_commit="$2"
airflow_version="$3"
secret_dir="$4"
base_url="$5"
execution_api_url="$6"

repo_accessible=false
git_status_ok=false
tracked_dirty_count=-1
current_commit=""
target_commit_available=false
secret_directory_contract_ok=false
runtime_secret_missing_count=0
runtime_secret_invalid_contract_count=0
compose_variant="none"
compose_config_ok=false
api_service=""
api_service_running=false
active_task_count_ok=false
active_task_instances=-1
business_baseline_output='{"ok":false,"read_only":true,"failure_category":"business_baseline_probe_unavailable"}'

if cd "$repo_path" 2>/dev/null; then
    repo_accessible=true
    if current_commit="$(git rev-parse HEAD 2>/dev/null)"; then
        :
    else
        current_commit=""
    fi
    if tracked_status="$(git status --porcelain --untracked-files=no 2>/dev/null)"; then
        git_status_ok=true
        if [ -z "$tracked_status" ]; then
            tracked_dirty_count=0
        else
            tracked_dirty_count="$(printf '%s\n' "$tracked_status" | awk 'END {print NR}')"
        fi
    fi
    if git cat-file -e "$target_commit^{commit}" 2>/dev/null; then
        target_commit_available=true
    fi
fi

if [ -d "$secret_dir" ]; then
    secret_directory_mode="$(stat -c '%a:%u:%g' "$secret_dir" 2>/dev/null || true)"
    if [ "$secret_directory_mode" = "750:0:0" ]; then
        secret_directory_contract_ok=true
    fi
fi

for filename in \
    airflow_fernet_key \
    airflow_api_secret_key \
    airflow_jwt_secret \
    airflow_database_password \
    airflow_admin_password; do
    secret_path="$secret_dir/$filename"
    if [ ! -s "$secret_path" ]; then
        runtime_secret_missing_count="$((runtime_secret_missing_count + 1))"
        continue
    fi
    secret_mode="$(stat -c '%a:%u:%g' "$secret_path" 2>/dev/null || true)"
    if [ "$secret_mode" != "640:0:0" ]; then
        runtime_secret_invalid_contract_count="$((runtime_secret_invalid_contract_count + 1))"
    fi
done

if docker compose version >/dev/null 2>&1; then
    compose_variant="plugin"
elif command -v docker-compose >/dev/null 2>&1; then
    compose_variant="legacy"
fi

short_commit="$(printf '%s' "$current_commit" | cut -c1-7)"
active_image="wechat-on-airflow:${airflow_version}-${short_commit:-unknown}"

compose() {
    if [ "$compose_variant" = "plugin" ]; then
        AIRFLOW_IMAGE_NAME="$active_image" \
        AIRFLOW_BASE_URL="$base_url" \
        AIRFLOW_EXECUTION_API_SERVER_URL="$execution_api_url" \
        AIRFLOW_SECRET_DIR="$secret_dir" \
        docker compose "$@"
    elif [ "$compose_variant" = "legacy" ]; then
        AIRFLOW_IMAGE_NAME="$active_image" \
        AIRFLOW_BASE_URL="$base_url" \
        AIRFLOW_EXECUTION_API_SERVER_URL="$execution_api_url" \
        AIRFLOW_SECRET_DIR="$secret_dir" \
        docker-compose "$@"
    else
        return 127
    fi
}

if [ "$repo_accessible" = true ] && [ "$compose_variant" != "none" ]; then
    if compose config --quiet </dev/null >/dev/null 2>&1; then
        compose_config_ok=true
        api_service="$(
            compose ps --services --status running 2>/dev/null \
                | awk '/^airflow-api-server$|^web$/{print; exit}'
        )"
        if [ -n "$api_service" ]; then
            api_service_running=true
            active_task_output="$(
                compose exec -T "$api_service" python - 2>/dev/null <<'PY'
import yaml
from sqlalchemy import func, select
from airflow.models.taskinstance import TaskInstance
from airflow.utils.session import create_session

ACTIVE_TASK_STATES = (
    "running",
    "queued",
    "scheduled",
    "restarting",
    "up_for_retry",
    "up_for_reschedule",
)

with open("/opt/airflow/project/config/active-components.yaml", encoding="utf-8") as handle:
    dag_ids = [item["dag_id"] for item in yaml.safe_load(handle)["active_dags"]]
with create_session() as session:
    count = session.scalar(
        select(func.count())
        .select_from(TaskInstance)
        .where(
            TaskInstance.dag_id.in_(dag_ids),
            TaskInstance.state.in_(ACTIVE_TASK_STATES),
        )
    )
print(int(count or 0))
PY
            )"
            active_task_rc="$?"
            active_task_candidate="$(printf '%s\n' "$active_task_output" | tail -n 1 | tr -d '\r')"
            if [ "$active_task_rc" -eq 0 ]; then
                case "$active_task_candidate" in
                    ''|*[!0-9]*) ;;
                    *)
                        active_task_count_ok=true
                        active_task_instances="$active_task_candidate"
                        ;;
                esac
            fi
        fi
    fi
fi

if [ "$repo_accessible" = true ] && [ "$compose_config_ok" = true ]; then
    business_baseline_output="$(
        compose exec -T zacks-api python - 2>/dev/null <<'BUSINESS_BASELINE_PY'
__BUSINESS_BASELINE_PROBE__
BUSINESS_BASELINE_PY
    )"
    if [ "$?" -ne 0 ]; then
        business_baseline_output='{"ok":false,"read_only":true,"failure_category":"business_baseline_probe_failed"}'
    fi
fi
export DIAG_BUSINESS_BASELINE="$business_baseline_output"

export DIAG_REPO_ACCESSIBLE="$repo_accessible"
export DIAG_GIT_STATUS_OK="$git_status_ok"
export DIAG_TRACKED_DIRTY_COUNT="$tracked_dirty_count"
export DIAG_CURRENT_COMMIT="$current_commit"
export DIAG_TARGET_COMMIT="$target_commit"
export DIAG_TARGET_AVAILABLE="$target_commit_available"
export DIAG_SECRET_DIRECTORY_OK="$secret_directory_contract_ok"
export DIAG_SECRET_MISSING_COUNT="$runtime_secret_missing_count"
export DIAG_SECRET_INVALID_COUNT="$runtime_secret_invalid_contract_count"
export DIAG_COMPOSE_VARIANT="$compose_variant"
export DIAG_COMPOSE_CONFIG_OK="$compose_config_ok"
export DIAG_API_SERVICE_RUNNING="$api_service_running"
export DIAG_ACTIVE_TASK_COUNT_OK="$active_task_count_ok"
export DIAG_ACTIVE_TASK_INSTANCES="$active_task_instances"

python3 - <<'PY'
import json
import os
import re
from datetime import datetime

def business_baseline(raw: str) -> dict:
    failure = {"ok": False, "read_only": True, "failure_category": "business_baseline_probe_failed"}
    try:
        value = json.loads(raw.strip().splitlines()[-1])
        if not isinstance(value, dict) or value.get("read_only") is not True or value.get("ok") is not True:
            return failure
        counts = {}
        for section, keys in (
            ("non_retired_stored_scopes", ("total_count", "healthy_count", "fresh_count", "healthy_and_fresh_count")),
            ("natural_delivery_last24h", ("email_delivered", "wechat_sent")),
        ):
            counts[section] = {}
            for key in keys:
                item = value[section][key]
                if not isinstance(item, int) or isinstance(item, bool) or not 0 <= item <= 10**18:
                    return failure
                counts[section][key] = item
        retired = value["retired_scope"]
        if retired.get("observation_key") != "szw:check_and_notify_day_3" or not isinstance(retired.get("present"), bool):
            return failure
        runtime = value["runtime"]
        timestamps = {"observed_at": value.get("observed_at"), "last_seen_at": retired.get("last_seen_at")}
        for key, item in timestamps.items():
            if key == "last_seen_at" and not retired["present"] and item is None:
                continue
            if not isinstance(item, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?[+-]\d{2}:\d{2}", item):
                return failure
            # Host Python is 3.6: fromisoformat and colon-bearing %z arrived later.
            normalized = item[:-3] + item[-2:]
            timestamp_format = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in item else "%Y-%m-%dT%H:%M:%S%z"
            datetime.strptime(normalized, timestamp_format)
        result = {
            "ok": True,
            "read_only": True,
            "purpose": "baseline_only_not_release_acceptance",
            "observed_at": timestamps["observed_at"],
            "window_hours": 24,
            "email_window_basis": "submitted_at",
            "wechat_window_basis": "sent_at",
            "freshness_minutes": 10,
            "scope_filter": "excludes_only_known_retired_szw_day_3",
            "retired_scope": {
                "observation_key": "szw:check_and_notify_day_3",
                "present": retired["present"],
                "healthy": retired.get("healthy") is True if retired["present"] else None,
                "fresh": retired.get("fresh") is True if retired["present"] else None,
                "last_seen_at": timestamps["last_seen_at"],
            },
            "runtime": {
                "delivery_enabled": runtime.get("delivery_enabled") is True,
                "wechat_enabled": runtime.get("wechat_enabled") is True,
                "activated": runtime.get("activated") is True,
            },
        }
        for key in ("container_commit", "control_commit"):
            item = runtime.get(key)
            result["runtime"][key] = item if isinstance(item, str) and re.fullmatch(r"[0-9a-f]{40}", item) else None
        result.update(counts)
        return result
    except (ValueError, KeyError, TypeError, IndexError, AttributeError):
        return failure



def flag(name: str) -> bool:
    return os.environ[name] == "true"


repo_accessible = flag("DIAG_REPO_ACCESSIBLE")
git_status_ok = flag("DIAG_GIT_STATUS_OK")
tracked_dirty_count = int(os.environ["DIAG_TRACKED_DIRTY_COUNT"])
secret_directory_ok = flag("DIAG_SECRET_DIRECTORY_OK")
secret_missing_count = int(os.environ["DIAG_SECRET_MISSING_COUNT"])
secret_invalid_count = int(os.environ["DIAG_SECRET_INVALID_COUNT"])
compose_variant = os.environ["DIAG_COMPOSE_VARIANT"]
compose_config_ok = flag("DIAG_COMPOSE_CONFIG_OK")
api_service_running = flag("DIAG_API_SERVICE_RUNNING")
active_task_count_ok = flag("DIAG_ACTIVE_TASK_COUNT_OK")
active_task_instances = int(os.environ["DIAG_ACTIVE_TASK_INSTANCES"])
baseline = business_baseline(os.environ["DIAG_BUSINESS_BASELINE"])

failed_stage = None
if not repo_accessible:
    failed_stage = "repository_path"
elif not git_status_ok:
    failed_stage = "repository_git_status"
elif tracked_dirty_count != 0:
    failed_stage = "repository_worktree_dirty"
elif not secret_directory_ok:
    failed_stage = "secret_directory_contract"
elif secret_missing_count:
    failed_stage = "runtime_secret_missing"
elif secret_invalid_count:
    failed_stage = "runtime_secret_contract"
elif compose_variant == "none":
    failed_stage = "compose_unavailable"
elif not compose_config_ok:
    failed_stage = "compose_config"
elif not api_service_running:
    failed_stage = "api_service_not_running"
elif not active_task_count_ok:
    failed_stage = "active_task_count"
elif baseline["ok"] is not True:
    failed_stage = "business_baseline_probe"

print(json.dumps({
    "ok": failed_stage is None,
    "failed_stage": failed_stage,
    "current_commit": os.environ["DIAG_CURRENT_COMMIT"] or None,
    "target_commit": os.environ["DIAG_TARGET_COMMIT"],
    "business_baseline": baseline,
    "checks": {
        "repository_accessible": repo_accessible,
        "git_status_ok": git_status_ok,
        "tracked_worktree_clean": tracked_dirty_count == 0,
        "tracked_dirty_count": tracked_dirty_count,
        "target_commit_already_available": flag("DIAG_TARGET_AVAILABLE"),
        "secret_directory_contract_ok": secret_directory_ok,
        "runtime_secret_missing_count": secret_missing_count,
        "runtime_secret_invalid_contract_count": secret_invalid_count,
        "compose_variant": compose_variant,
        "compose_config_ok": compose_config_ok,
        "api_service_running": api_service_running,
        "active_task_count_ok": active_task_count_ok,
        "active_task_instances": active_task_instances if active_task_count_ok else None,
    },
}, sort_keys=True))
PY
"""
    return script.replace("__BUSINESS_BASELINE_PROBE__", BUSINESS_BASELINE_PROBE)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Diagnose the read-only Airflow deployment preflight contract."
    )
    parser.add_argument("--target-commit", default="HEAD")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    target_commit = resolve_target_commit(args.target_commit)
    runtime_target = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    remote = airflow_remote()
    command = [
        *ssh_command(remote),
        "bash",
        "-s",
        "--",
        remote["repository_path"],
        target_commit,
        str(runtime_target["target"]["airflow"]),
        str(runtime_target["target"]["production_secret_directory"]),
        str(runtime_target["managed_services"]["cloudflare_tunnel"]["public_base_url"]),
        str(runtime_target["target"]["execution_api_server_url"]),
    ]
    result = run(command, check=False, input_text=remote_script())
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else "remote Airflow preflight diagnosis failed"
        raise OpsError(message)

    payload = parse_remote_result(result.stdout)
    emit(payload, args.format)
    if not payload.get("ok"):
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"diagnose-airflow-deploy-preflight: {exc}")
        raise SystemExit(1) from exc
