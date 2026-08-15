#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import shlex

from _ops import OpsError, airflow_remote, emit, run, ssh_command

VARIABLE_NAME = "NSWTT_API_CONFIG"
REQUIRED_FIELDS = {"app_version", "cookie"}
ALLOWED_FIELDS = {
    "app_version",
    "base_url",
    "cookie",
    "page_path",
    "page_uuid",
    "project_id",
    "timeout_seconds",
}


def validated_config(raw: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OpsError("NSWTT_API_CONFIG is not valid JSON") from exc
    if not isinstance(value, dict):
        raise OpsError("NSWTT_API_CONFIG must be a JSON object")
    missing = sorted(field for field in REQUIRED_FIELDS if not value.get(field))
    unexpected = sorted(set(value) - ALLOWED_FIELDS)
    if missing:
        raise OpsError(f"NSWTT_API_CONFIG is missing fields: {', '.join(missing)}")
    if unexpected:
        raise OpsError(f"NSWTT_API_CONFIG has unsupported fields: {', '.join(unexpected)}")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def sync(config_json: str) -> dict[str, object]:
    remote = airflow_remote()
    remote_script = r"""
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
service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
test -n "$service"
compose exec -T "$service" python -c '
import json
import sys
from airflow.models.variable import Variable

value = json.load(sys.stdin)
Variable.set("NSWTT_API_CONFIG", json.dumps(value, ensure_ascii=False, separators=(",", ":")))
'
compose exec -T "$service" python -c '
import json
from airflow.models.variable import Variable

value = json.loads(Variable.get("NSWTT_API_CONFIG"))
assert value.get("app_version") and value.get("cookie")
'
"""
    script_base64 = base64.b64encode(remote_script.encode()).decode()
    repository_path = shlex.quote(remote["repository_path"])
    remote_command = (
        "tmp=$(mktemp); trap 'rm -f \"$tmp\"' EXIT; "
        f'printf %s {shlex.quote(script_base64)} | base64 -d > "$tmp"; '
        f'bash "$tmp" {repository_path}'
    )
    run([*ssh_command(remote), remote_command], input_text=config_json)
    return {"ok": True, "variable": VARIABLE_NAME, "fields": sorted(json.loads(config_json))}


def main() -> None:
    raw = os.environ.get("NSWTT_API_CONFIG", "")
    if not raw:
        raise OpsError("missing required environment key: NSWTT_API_CONFIG")
    emit(sync(validated_config(raw)), "json")


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"sync-nswtt-config: {exc}")
        raise SystemExit(1) from exc
