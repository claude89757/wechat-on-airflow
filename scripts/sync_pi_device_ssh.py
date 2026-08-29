#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import shlex

from _ops import OpsError, airflow_remote, emit, run, ssh_command

VARIABLE_NAME = "PI_DEVICE_SSH"
REQUIRED_ENV = {
    "host": "PI_DEVICE_SSH_HOST",
    "port": "PI_DEVICE_SSH_PORT",
    "username": "PI_DEVICE_SSH_USER",
    "password": "PI_DEVICE_SSH_PASSWORD",
    "host_key_sha256": "PI_DEVICE_SSH_HOST_KEY_SHA256",
}
REQUIRED_FIELDS = tuple(REQUIRED_ENV)


def validated_config(raw_fields: dict[str, str]) -> str:
    host = raw_fields.get("host", "").strip()
    username = raw_fields.get("username", "").strip()
    password = raw_fields.get("password", "")
    host_key = raw_fields.get("host_key_sha256", "").strip()
    raw_port = str(raw_fields.get("port", "")).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise OpsError("PI_DEVICE_SSH.port must be an integer") from exc
    if not host or not username or not password or not host_key or port <= 0:
        raise OpsError("PI_DEVICE_SSH is missing required SSH fields")
    return json.dumps(
        {
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "host_key_sha256": host_key,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


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
Variable.set("PI_DEVICE_SSH", json.dumps(value, ensure_ascii=False, separators=(",", ":")))
'
compose exec -T "$service" python -c '
import json
from airflow.models.variable import Variable

value = json.loads(Variable.get("PI_DEVICE_SSH"))
required = ("host", "port", "username", "password", "host_key_sha256")
assert all(value.get(field) for field in required)
assert int(value["port"]) > 0
print(json.dumps({"ok": True, "fields": sorted(value.keys())}))
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
    return {
        "ok": True,
        "variable": VARIABLE_NAME,
        "fields": sorted(json.loads(config_json)),
    }


def config_from_environment() -> dict[str, str]:
    missing = sorted(
        env_name for env_name in REQUIRED_ENV.values() if not os.environ.get(env_name, "")
    )
    if missing:
        raise OpsError("missing required environment keys: " + ", ".join(missing))
    return {field: os.environ[env_name] for field, env_name in REQUIRED_ENV.items()}


def main() -> None:
    emit(sync(validated_config(config_from_environment())), "json")


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"sync-pi-device-ssh: {exc}")
        raise SystemExit(1) from exc
