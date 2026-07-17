#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Any

import yaml
from _ops import REPO_ROOT, OpsError, emit, merged_env, required_env, run

MARKERS = (
    "commit",
    "compose",
    "airflow_version",
    "import_errors",
    "dags",
    "variables",
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
    dag_ids = [component["dag_id"] for component in manifest["active_dags"]]
    required_variable_names = sorted(
        name
        for name, contract in contracts["variables"].items()
        if not contract.get("managed_by_application") and "default" not in contract
    )
    target_airflow = str(runtime_target["target"]["airflow"])
    expected_services = set(runtime_target["target"]["services"])
    recent_run_count = int(runtime_target["verification"]["production_cycles"])
    sender_health_url = str(
        runtime_target["managed_services"]["wechat_sender"]["production_health_url"]
    )

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
printf '__IMPORT_ERRORS__\n'
compose exec -T "$service" airflow dags list-import-errors --output json </dev/null || true
printf '__DAGS__\n'
airflow_python - <<'PY'
import json
from airflow.models.dag import DagModel
from airflow.utils.session import create_session

with create_session() as session:
    rows = session.query(DagModel.dag_id, DagModel.is_paused).all()
print(
    json.dumps(
        [{"dag_id": dag_id, "is_paused": bool(is_paused)} for dag_id, is_paused in rows],
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
try:
    from airflow.sdk import Variable
except ImportError:
    from airflow.models import Variable
result = {}
for key in ("EMAIL_SEND_FALLBACK_OUTBOX", "WECHAT_SEND_FALLBACK_OUTBOX"):
    try:
        value = Variable.get(key, default_var=[], deserialize_json=True)
        result[key] = len(value) if isinstance(value, list) else None
    except Exception:
        result[key] = None
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
python3 - <<'PY'
import json
import urllib.request

result = {"wechat_sender": {"ok": False}}
try:
    response = urllib.request.urlopen(__SENDER_HEALTH_URL__, timeout=5)
    payload = json.loads(response.read().decode("utf-8"))
    result["wechat_sender"] = {
        "ok": response.getcode() == 200 and payload.get("ok") is True,
        "status_code": response.getcode(),
    }
except Exception as exc:
    result["wechat_sender"]["error_type"] = type(exc).__name__
print(json.dumps(result, sort_keys=True))
PY
"""
    remote_script = remote_script.replace(
        "__DAG_IDS_JSON__", repr(json.dumps(dag_ids, ensure_ascii=True))
    ).replace("__RUN_COUNT__", str(recent_run_count))
    remote_script = remote_script.replace("__SENDER_HEALTH_URL__", repr(sender_health_url))
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
        "StrictHostKeyChecking=accept-new",
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
    import_errors = parse_json_output(sections["import_errors"], [])
    dags = parse_json_output(sections["dags"], [])
    variable_names = parse_json_output(sections["variables"], [])
    recent_runs = parse_json_output(sections["recent_runs"], {})
    outboxes = parse_json_output(sections["outboxes"], {})
    database = parse_json_output(sections["database"], {})
    storage = parse_json_output(sections["storage"], {})
    managed_services = parse_json_output(sections["managed_services"], {})
    parsed_ids = {
        item.get("dag_id") for item in dags if isinstance(item, dict) and item.get("dag_id")
    }
    missing_dags = sorted(set(dag_ids) - parsed_ids)
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
        runs = recent_runs.get(dag_id, []) if isinstance(recent_runs, dict) else []
        valid_runs = [run for run in runs if isinstance(run, dict)]
        recent_run_summary[dag_id] = valid_runs
        states = [str(run.get("state", "")).lower() for run in valid_runs]
        if len(valid_runs) < recent_run_count or any(state != "success" for state in states):
            recent_run_failures[dag_id] = {
                "observed_count": len(valid_runs),
                "required_count": recent_run_count,
                "states": states,
            }

    outbox_failures = (
        {name: count for name, count in outboxes.items() if not isinstance(count, int) or count > 0}
        if isinstance(outboxes, dict)
        else {"outboxes": None}
    )

    issues: list[dict[str, str]] = []

    def add_issue(component: str, detail: str, remediation: str) -> None:
        issues.append(
            {
                "component": component,
                "detail": detail,
                "remediation": remediation,
            }
        )

    airflow_version = sections["airflow_version"].splitlines()[-1].strip()
    if airflow_version != target_airflow:
        add_issue(
            "airflow_version",
            f"deployed {airflow_version}, target {target_airflow}",
            "deploy the pinned target image and run the documented database migration",
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
    if paused_dags:
        add_issue(
            "active_dags",
            f"paused DAGs: {', '.join(paused_dags)}",
            "confirm migration checks are complete, then unpause the active DAGs",
        )
    if missing_variables:
        add_issue(
            "configuration",
            f"missing Variable names: {', '.join(missing_variables)}",
            "create the missing Variables without printing or committing their values",
        )
    if recent_run_failures:
        add_issue(
            "recent_dag_runs",
            f"{len(recent_run_failures)} DAGs lack the required successful run history",
            "inspect failed task logs and verify three completed successful cycles",
        )
    if outbox_failures:
        add_issue(
            "notification_fallback",
            f"fallback outbox backlog: {json.dumps(outbox_failures, sort_keys=True)}",
            "resolve delivery, then archive or clear records through an approved no-replay procedure",
        )
    database_bytes = database.get("database_bytes") if isinstance(database, dict) else None
    storage_free_bytes = storage.get("free_bytes") if isinstance(storage, dict) else None
    migration_disk_headroom = (
        isinstance(database_bytes, int)
        and isinstance(storage_free_bytes, int)
        and storage_free_bytes > database_bytes
    )
    if airflow_version != target_airflow and migration_disk_headroom is False:
        add_issue(
            "migration_storage",
            "free root-disk space is not greater than the metadata database size",
            "add reliable disk capacity or use an approved restore-based compact migration",
        )
    sender_health = (
        managed_services.get("wechat_sender") if isinstance(managed_services, dict) else None
    )
    if not isinstance(sender_health, dict) or sender_health.get("ok") is not True:
        add_issue(
            "wechat_sender",
            "managed WeChat sender health check failed",
            "start docker-compose.sender.yml and verify its /healthz endpoint",
        )

    payload = {
        "ok": not issues,
        "deployed_commit": sections["commit"].strip(),
        "airflow_version": airflow_version,
        "target_airflow_version": target_airflow,
        "service_count": len(compose_rows),
        "unhealthy_services": unhealthy_services,
        "missing_target_services": missing_services,
        "import_error_count": import_error_count,
        "missing_active_dags": missing_dags,
        "paused_active_dags": paused_dags,
        "missing_required_variable_names": missing_variables,
        "recent_runs": recent_run_summary,
        "recent_run_failures": recent_run_failures,
        "fallback_outbox_counts": outboxes,
        "database": database,
        "storage": storage,
        "migration_disk_headroom": migration_disk_headroom,
        "managed_services": managed_services,
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
