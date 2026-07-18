#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, emit, merged_env, required_env, run

MARKERS = (
    "commit",
    "compose",
    "airflow_version",
    "execution_api",
    "import_errors",
    "dags",
    "dag_sources",
    "variables",
    "variable_contracts",
    "recent_runs",
    "outboxes",
    "database",
    "storage",
    "managed_services",
)


def parse_sections(output: str) -> dict[str, str]:
    sections = {marker: "" for marker in MARKERS}
    current: str | None = None
    lines: list[str] = []
    for line in output.splitlines():
        if line.startswith("__") and line.endswith("__"):
            if current is not None:
                sections[current] = "\n".join(lines).strip()
            marker = line.strip("_").lower()
            current = marker if marker in sections else None
            lines = []
        elif current is not None:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines).strip()
    return sections


def parse_json_output(value: str, default: Any) -> Any:
    for index, char in enumerate(value):
        if char not in "[{":
            continue
        try:
            return json.loads(value[index:])
        except json.JSONDecodeError:
            continue
    return default


def parse_compose_rows(value: str) -> list[dict[str, Any]]:
    line_rows = []
    for line in value.splitlines():
        if not line.strip().startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            line_rows.append(row)
    if line_rows:
        return line_rows

    parsed = parse_json_output(value, None)
    if isinstance(parsed, list):
        return [row for row in parsed if isinstance(row, dict)]
    if isinstance(parsed, dict):
        return [parsed]
    return []


def normalized_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def required_successful_run_counts(
    active_dags: list[dict[str, Any]],
    production_cycles: int,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for component in active_dags:
        verification = set(component.get("verification") or [])
        if "recent_runs_succeed" in verification:
            counts[str(component["dag_id"])] = production_cycles
        elif "latest_run_succeeds" in verification:
            counts[str(component["dag_id"])] = 1
        else:
            counts[str(component["dag_id"])] = 0
    return counts


def deployment_commit_matches(expected_commit: str, deployed_commit: str) -> bool:
    return len(expected_commit) == 40 and expected_commit == deployed_commit


def classify_fallback_outboxes(
    outboxes: dict[str, Any],
    *,
    now: datetime,
    grace_minutes: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    recent: dict[str, Any] = {}
    historical: dict[str, Any] = {}
    malformed: dict[str, Any] = {}
    cutoff = now.astimezone(UTC) - timedelta(minutes=grace_minutes)
    for name, details in outboxes.items():
        if not isinstance(details, dict):
            malformed[name] = details
            continue
        count = details.get("count")
        latest_value = details.get("latest_failed_at")
        if not isinstance(count, int) or count < 0:
            malformed[name] = details
            continue
        if count == 0:
            continue
        if not isinstance(latest_value, str):
            malformed[name] = details
            continue
        try:
            latest = datetime.fromisoformat(latest_value).astimezone(UTC)
        except ValueError:
            malformed[name] = details
            continue
        target = recent if latest >= cutoff else historical
        target[name] = {"count": count, "latest_failed_at": latest.isoformat()}
    return recent, historical, malformed


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only production Airflow health check.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    values = merged_env()
    remote = required_env(values, ["SERVER_IP", "PORT", "USERNAME", "PASSWORD", "REMOTE_PATH"])
    manifest = yaml.safe_load(
        (REPO_ROOT / "config" / "active-components.yaml").read_text(encoding="utf-8")
    )
    contracts = yaml.safe_load(
        (REPO_ROOT / "config" / "config-contracts.yaml").read_text(encoding="utf-8")
    )
    runtime_target = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    expected_commit = run(["git", "rev-parse", "HEAD"]).stdout.strip()
    active_dags = manifest["active_dags"]
    dag_ids = [component["dag_id"] for component in active_dags]
    dag_source_paths = [
        str(component["file"]).removeprefix("dags/") for component in manifest["active_dags"]
    ]
    required_variable_names = sorted(
        name
        for name, contract in contracts["variables"].items()
        if not contract.get("managed_by_application") and "default" not in contract
    )
    target_airflow = str(runtime_target["target"]["airflow"])
    expected_services = set(runtime_target["target"]["services"])
    database_target = runtime_target["target"]["database"]
    deployment_strategy = str(database_target["deployment_strategy"])
    minimum_free_bytes = int(database_target["minimum_free_bytes"])
    recent_run_count = int(runtime_target["verification"]["production_cycles"])
    fallback_grace_minutes = int(
        runtime_target["verification"]["notification_failure_grace_minutes"]
    )
    required_run_counts = required_successful_run_counts(active_dags, recent_run_count)
    queried_run_count = max(required_run_counts.values(), default=0)
    sender_target = runtime_target["managed_services"]["wechat_sender"]
    sender_endpoint_variable = str(sender_target["endpoint_variable"])
    sender_readiness_path = str(sender_target["readiness_path"])

    remote_script = r"""
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
airflow_python() {
    compose exec -T "$service" sh -c '
        if [ -x /opt/bitnami/airflow/venv/bin/python ]; then
            exec /opt/bitnami/airflow/venv/bin/python "$@"
        fi
        exec python "$@"
    ' sh "$@"
}
printf '__COMMIT__\n'
git rev-parse HEAD
printf '__COMPOSE__\n'
compose ps --format json
printf '__AIRFLOW_VERSION__\n'
compose exec -T "$service" airflow version </dev/null
printf '__EXECUTION_API__\n'
airflow_python - <<'PY'
import json
import urllib.error
import urllib.request
from airflow.configuration import conf

base_url = conf.get("core", "execution_api_server_url").rstrip("/")
request = urllib.request.Request(
    f"{base_url}/task-instances/00000000-0000-0000-0000-000000000000/run",
    data=b"{}",
    headers={"Content-Type": "application/json"},
    method="PATCH",
)
try:
    response = urllib.request.urlopen(request, timeout=5)
    status_code = response.getcode()
except urllib.error.HTTPError as exc:
    status_code = exc.code
except Exception:
    status_code = None
print(json.dumps({"ok": status_code == 401, "status_code": status_code}, sort_keys=True))
PY
printf '__IMPORT_ERRORS__\n'
compose exec -T "$service" airflow dags list-import-errors --output json </dev/null || true
printf '__DAGS__\n'
airflow_python - <<'PY'
import json
from airflow.models.dag import DagModel
from airflow.utils.session import create_session

with create_session() as session:
    rows = session.query(DagModel.dag_id, DagModel.is_paused, DagModel.is_stale).all()
print(
    json.dumps(
        [
            {
                "dag_id": dag_id,
                "is_paused": bool(is_paused),
                "is_active": not bool(is_stale),
            }
            for dag_id, is_paused, is_stale in rows
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY
printf '__DAG_SOURCES__\n'
airflow_python - <<'PY'
import json
import os
from pathlib import Path

root = Path("/opt/airflow/dags")
expected = json.loads(__DAG_SOURCE_PATHS_JSON__)
missing = []
unreadable = []
for relative_path in expected:
    path = root / relative_path
    if not path.is_file():
        missing.append(relative_path)
    elif not os.access(path, os.R_OK):
        unreadable.append(relative_path)
print(
    json.dumps(
        {
            "expected_count": len(expected),
            "missing": missing,
            "unreadable": unreadable,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
)
PY
printf '__VARIABLES__\n'
airflow_python - <<'PY'
import json
from airflow.models.variable import Variable
from airflow.utils.session import create_session

with create_session() as session:
    names = sorted(key for (key,) in session.query(Variable.key).all())
print(json.dumps(names, ensure_ascii=False))
PY
printf '__VARIABLE_CONTRACTS__\n'
airflow_python - <<'PY'
import base64
import hashlib
import json
from airflow.models.variable import Variable


def matches_zacks(item):
    exact_fields = ("wx_user_id", "wx_id", "wx_name", "name")
    exact_values = {
        str(item.get(field, "")).strip().lower()
        for field in exact_fields
        if str(item.get(field, "")).strip()
    }
    return "zacks" in exact_values or "zacks" in str(item.get("dag_id", "")).lower()


def valid_sha256_fingerprint(value):
    if not isinstance(value, str) or not value.startswith("SHA256:"):
        return False
    encoded = value.removeprefix("SHA256:").rstrip("=")
    try:
        digest = base64.b64decode(encoded + ("=" * (-len(encoded) % 4)), validate=True)
    except Exception:
        return False
    return len(digest) == hashlib.sha256().digest_size


try:
    appium_servers = Variable.get("APPIUM_SERVER_LIST", default_var=[], deserialize_json=True)
except Exception:
    appium_servers = None
items = [item for item in appium_servers if isinstance(item, dict)] if isinstance(appium_servers, list) else []
targets = [item for item in items if matches_zacks(item)]
login_info = targets[0].get("login_info", {}) if len(targets) == 1 else {}
print(
    json.dumps(
        {
            "APPIUM_SERVER_LIST": {
                "is_list": isinstance(appium_servers, list),
                "zacks_target_count": len(targets),
                "host_key_sha256_valid": valid_sha256_fingerprint(
                    login_info.get("host_key_sha256")
                ),
            }
        },
        sort_keys=True,
    )
)
PY
printf '__RECENT_RUNS__\n'
airflow_python - <<'PY'
import json
from airflow.models.dagrun import DagRun
from airflow.utils.session import create_session

DAG_IDS = json.loads(__DAG_IDS_JSON__)
RUN_COUNT = __RUN_COUNT__
date_name = (
    "logical_date"
    if "logical_date" in DagRun.__table__.columns
    else "execution_date"
)
date_column = getattr(DagRun, date_name)

result = {}
with create_session() as session:
    for dag_id in DAG_IDS:
        rows = (
            session.query(DagRun)
            .filter(DagRun.dag_id == dag_id, DagRun.state.in_(("success", "failed")))
            .order_by(date_column.desc(), DagRun.id.desc())
            .limit(RUN_COUNT)
            .all()
        )
        result[dag_id] = [
            {
                "run_id": row.run_id,
                "state": str(row.state),
                "logical_date": getattr(row, date_name).isoformat(),
            }
            for row in rows
        ]
print(json.dumps(result, ensure_ascii=False, sort_keys=True))
PY
printf '__OUTBOXES__\n'
airflow_python - <<'PY'
import json
from airflow.models.variable import Variable
result = {}
for key in ("EMAIL_SEND_FALLBACK_OUTBOX", "WECHAT_SEND_FALLBACK_OUTBOX"):
    try:
        value = Variable.get(key, default_var=[], deserialize_json=True)
        if not isinstance(value, list):
            result[key] = {"count": None, "latest_failed_at": None}
            continue
        timestamps = [
            item.get("last_failed_at")
            for item in value
            if isinstance(item, dict) and isinstance(item.get("last_failed_at"), str)
        ]
        result[key] = {
            "count": len(value),
            "latest_failed_at": max(timestamps) if timestamps else None,
        }
    except Exception:
        result[key] = {"count": None, "latest_failed_at": None}
print(json.dumps(result, sort_keys=True))
PY
printf '__DATABASE__\n'
airflow_python - <<'PY'
import json
from sqlalchemy import text
from airflow.utils.session import create_session

relations = ("task_instance", "dag_run", "xcom", "log")
with create_session() as session:
    database_bytes = session.execute(
        text("SELECT pg_database_size(current_database())")
    ).scalar_one()
    relation_rows = session.execute(
        text(
            "SELECT relname, pg_total_relation_size(oid) "
            "FROM pg_class "
            "WHERE relname = ANY(:relations) AND relkind = 'r' "
            "ORDER BY relname"
        ),
        {"relations": list(relations)},
    ).all()
    revision = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
print(
    json.dumps(
        {
            "database_bytes": int(database_bytes),
            "schema_revision": str(revision),
            "relations": {name: int(size) for name, size in relation_rows},
        },
        sort_keys=True,
    )
)
PY
printf '__STORAGE__\n'
df -PB1 / | awk 'NR == 2 {printf "{\"total_bytes\":%s,\"used_bytes\":%s,\"free_bytes\":%s}\n", $2, $3, $4}'
printf '__MANAGED_SERVICES__\n'
airflow_python - <<'PY'
import json
import urllib.error
import urllib.parse
import urllib.request
from airflow.models.variable import Variable

result = {"wechat_sender": {"ok": False, "configured": False}}
try:
    endpoint = str(Variable.get(__SENDER_ENDPOINT_VARIABLE__, default_var="")).strip()
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("sender endpoint is missing or invalid")
    readiness_url = urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, __SENDER_READINESS_PATH__, "", "")
    )
    result["wechat_sender"]["configured"] = True
    response = urllib.request.urlopen(readiness_url, timeout=5)
    payload = json.loads(response.read().decode("utf-8"))
    result["wechat_sender"] = {
        "ok": response.getcode() == 200 and payload.get("ok") is True,
        "configured": True,
        "status_code": response.getcode(),
    }
except urllib.error.HTTPError as exc:
    result["wechat_sender"] = {
        "ok": False,
        "configured": True,
        "status_code": exc.code,
        "error_type": type(exc).__name__,
    }
except Exception as exc:
    result["wechat_sender"]["error_type"] = type(exc).__name__
print(json.dumps(result, sort_keys=True))
PY
"""
    remote_script = (
        remote_script.replace("__DAG_IDS_JSON__", repr(json.dumps(dag_ids, ensure_ascii=True)))
        .replace(
            "__DAG_SOURCE_PATHS_JSON__",
            repr(json.dumps(dag_source_paths, ensure_ascii=True)),
        )
        .replace("__RUN_COUNT__", str(queried_run_count))
    )
    remote_script = remote_script.replace(
        "__SENDER_ENDPOINT_VARIABLE__", repr(sender_endpoint_variable)
    ).replace("__SENDER_READINESS_PATH__", repr(sender_readiness_path))
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
    ]
    result = run(command, env=ssh_env, check=False, input_text=remote_script)
    if result.returncode:
        raise OpsError(result.stderr.strip() or "production SSH health command failed")

    sections = parse_sections(result.stdout)
    compose_rows = parse_compose_rows(sections["compose"])
    execution_api = parse_json_output(sections["execution_api"], {})
    import_errors = parse_json_output(sections["import_errors"], [])
    dags = parse_json_output(sections["dags"], [])
    dag_sources = parse_json_output(sections["dag_sources"], {})
    variable_names = parse_json_output(sections["variables"], [])
    variable_contracts = parse_json_output(sections["variable_contracts"], {})
    recent_runs = parse_json_output(sections["recent_runs"], {})
    outboxes = parse_json_output(sections["outboxes"], {})
    database = parse_json_output(sections["database"], {})
    storage = parse_json_output(sections["storage"], {})
    managed_services = parse_json_output(sections["managed_services"], {})
    active_parsed_ids = {
        item.get("dag_id")
        for item in dags
        if isinstance(item, dict) and item.get("dag_id") and normalized_bool(item.get("is_active"))
    }
    missing_dags = sorted(set(dag_ids) - active_parsed_ids)
    unexpected_active_dags = sorted(active_parsed_ids - set(dag_ids))
    missing_dag_sources = (
        sorted(str(path) for path in dag_sources.get("missing", []))
        if isinstance(dag_sources, dict) and isinstance(dag_sources.get("missing"), list)
        else dag_source_paths
    )
    unreadable_dag_sources = (
        sorted(str(path) for path in dag_sources.get("unreadable", []))
        if isinstance(dag_sources, dict) and isinstance(dag_sources.get("unreadable"), list)
        else dag_source_paths
    )
    paused_dags = sorted(
        item["dag_id"]
        for item in dags
        if isinstance(item, dict)
        and item.get("dag_id") in dag_ids
        and normalized_bool(item.get("is_paused"))
    )
    present_services = {
        str(row.get("Service") or row.get("Name") or "")
        for row in compose_rows
        if row.get("Service") or row.get("Name")
    }
    missing_services = sorted(expected_services - present_services)
    unhealthy_services = [
        row.get("Service") or row.get("Name")
        for row in compose_rows
        if str(row.get("State", "")).lower() != "running"
        or str(row.get("Health") or "").lower() not in ("", "healthy")
    ]
    if isinstance(import_errors, list | dict):
        import_error_count = len(import_errors)
    else:
        import_error_count = -1
    present_variable_names = {str(name) for name in variable_names if isinstance(name, str)}
    missing_variables = sorted(set(required_variable_names) - present_variable_names)

    recent_run_failures: dict[str, dict[str, Any]] = {}
    recent_run_summary: dict[str, list[dict[str, Any]]] = {}
    for dag_id in dag_ids:
        required_count = required_run_counts[dag_id]
        runs = recent_runs.get(dag_id, []) if isinstance(recent_runs, dict) else []
        valid_runs = [run for run in runs if isinstance(run, dict)]
        recent_run_summary[dag_id] = valid_runs
        relevant_runs = valid_runs[:required_count]
        states = [str(run.get("state", "")).lower() for run in relevant_runs]
        if required_count and (
            len(relevant_runs) < required_count or any(state != "success" for state in states)
        ):
            recent_run_failures[dag_id] = {
                "observed_count": len(relevant_runs),
                "required_count": required_count,
                "states": states,
            }

    recent_outbox_failures, historical_outboxes, malformed_outboxes = classify_fallback_outboxes(
        outboxes if isinstance(outboxes, dict) else {"outboxes": outboxes},
        now=datetime.now(UTC),
        grace_minutes=fallback_grace_minutes,
    )
    outbox_counts = (
        {
            name: details.get("count") if isinstance(details, dict) else None
            for name, details in outboxes.items()
        }
        if isinstance(outboxes, dict)
        else {}
    )

    issues: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def add_issue(component: str, detail: str, remediation: str) -> None:
        issues.append(
            {
                "component": component,
                "detail": detail,
                "remediation": remediation,
            }
        )

    def add_warning(component: str, detail: str, remediation: str) -> None:
        warnings.append(
            {
                "component": component,
                "detail": detail,
                "remediation": remediation,
            }
        )

    deployed_commit = sections["commit"].strip()
    airflow_version = sections["airflow_version"].splitlines()[-1].strip()
    if not deployment_commit_matches(expected_commit, deployed_commit):
        add_issue(
            "deployed_commit",
            f"deployed {deployed_commit}, expected local HEAD {expected_commit}",
            "deploy the exact pushed local HEAD with make deploy",
        )
    if airflow_version != target_airflow:
        add_issue(
            "airflow_version",
            f"deployed {airflow_version}, target {target_airflow}",
            "deploy the pinned target image with the documented fresh metadata database",
        )
    if unhealthy_services:
        add_issue(
            "compose_services",
            f"unhealthy services: {', '.join(str(name) for name in unhealthy_services)}",
            "inspect compose service health and logs before continuing",
        )
    if missing_services:
        add_issue(
            "compose_topology",
            f"missing target services: {', '.join(missing_services)}",
            "deploy the Airflow 3 compose topology from the pushed commit",
        )
    if not isinstance(execution_api, dict) or execution_api.get("ok") is not True:
        add_issue(
            "execution_api",
            f"internal unauthenticated route probe failed: {execution_api}",
            "include the public API path prefix in AIRFLOW_EXECUTION_API_SERVER_URL",
        )
    if missing_dag_sources or unreadable_dag_sources:
        add_issue(
            "dag_sources",
            "missing or unreadable image DAG files: "
            f"missing={missing_dag_sources}, unreadable={unreadable_dag_sources}",
            "rebuild the pinned Airflow image and verify its DAG source permissions",
        )
    if import_error_count:
        add_issue(
            "dag_imports",
            f"import error count: {import_error_count}",
            "run make test-dags and inspect Airflow import errors",
        )
    if missing_dags:
        add_issue(
            "active_dags",
            f"missing DAGs: {', '.join(missing_dags)}",
            "compare config/active-components.yaml with the deployed DAG bundle",
        )
    if unexpected_active_dags:
        add_issue(
            "active_dags",
            f"unexpected active DAGs: {', '.join(unexpected_active_dags)}",
            "pause retired DAGs and wait for the deployed DagBag to mark them inactive",
        )
    if paused_dags:
        add_issue(
            "active_dags",
            f"paused DAGs: {', '.join(paused_dags)}",
            "satisfy each DAG's external prerequisites before unpausing it",
        )
    if missing_variables:
        add_issue(
            "configuration",
            f"missing Variable names: {', '.join(missing_variables)}",
            "create the missing Variables without printing or committing their values",
        )
    appium_contract = (
        variable_contracts.get("APPIUM_SERVER_LIST")
        if isinstance(variable_contracts, dict)
        else None
    )
    if (
        not isinstance(appium_contract, dict)
        or appium_contract.get("is_list") is not True
        or appium_contract.get("zacks_target_count") != 1
        or appium_contract.get("host_key_sha256_valid") is not True
    ):
        add_issue(
            "android_host_key",
            "APPIUM_SERVER_LIST does not contain one Zacks target with a valid pinned host key",
            "verify the SSH key out of band, then configure login_info.host_key_sha256",
        )
    if recent_run_failures:
        add_issue(
            "recent_dag_runs",
            f"{len(recent_run_failures)} DAGs lack the required successful run history",
            "inspect failed task logs and verify three completed successful cycles",
        )
    if malformed_outboxes:
        add_issue(
            "notification_fallback",
            f"malformed fallback outbox state: {json.dumps(malformed_outboxes, sort_keys=True)}",
            "repair the outbox contract without replaying or dropping incident records",
        )
    if recent_outbox_failures:
        add_issue(
            "notification_fallback",
            f"recent fallback failures: {json.dumps(recent_outbox_failures, sort_keys=True)}",
            "repair the affected channel and verify new failures stop accumulating",
        )
    if historical_outboxes:
        add_warning(
            "notification_fallback_history",
            f"historical fallback records retained: {json.dumps(historical_outboxes, sort_keys=True)}",
            "retain as incident evidence; archive only through an approved no-replay procedure",
        )
    storage_free_bytes = storage.get("free_bytes") if isinstance(storage, dict) else None
    deployment_storage_ready = (
        isinstance(storage_free_bytes, int) and storage_free_bytes >= minimum_free_bytes
    )
    if airflow_version != target_airflow and deployment_storage_ready is False:
        add_issue(
            "deployment_storage",
            f"free root-disk space is below the {minimum_free_bytes}-byte fresh-start floor",
            "add reliable disk capacity without deleting the preserved Airflow 2 database",
        )
    sender_health = (
        managed_services.get("wechat_sender") if isinstance(managed_services, dict) else None
    )
    if not isinstance(sender_health, dict) or sender_health.get("ok") is not True:
        add_issue(
            "wechat_sender",
            "managed WeChat sender health check failed",
            "repair wechat-sender.service on the Android device host and verify /readyz",
        )

    payload = {
        "ok": not issues,
        "expected_commit": expected_commit,
        "deployed_commit": deployed_commit,
        "airflow_version": airflow_version,
        "target_airflow_version": target_airflow,
        "service_count": len(compose_rows),
        "unhealthy_services": unhealthy_services,
        "missing_target_services": missing_services,
        "execution_api": execution_api,
        "import_error_count": import_error_count,
        "missing_dag_sources": missing_dag_sources,
        "unreadable_dag_sources": unreadable_dag_sources,
        "missing_active_dags": missing_dags,
        "unexpected_active_dags": unexpected_active_dags,
        "paused_active_dags": paused_dags,
        "missing_required_variable_names": missing_variables,
        "variable_contracts": variable_contracts,
        "recent_runs": recent_run_summary,
        "recent_run_failures": recent_run_failures,
        "fallback_outbox_counts": outbox_counts,
        "fallback_outboxes": outboxes,
        "database": database,
        "storage": storage,
        "deployment_strategy": deployment_strategy,
        "deployment_storage_ready": deployment_storage_ready,
        "managed_services": managed_services,
        "warnings": warnings,
        "issues": issues,
    }
    emit(payload, args.format)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        raise SystemExit(1) from exc
