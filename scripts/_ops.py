from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


class OpsError(RuntimeError):
    pass


def run(
    command: list[str],
    *,
    cwd: Path = REPO_ROOT,
    check: bool = True,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        input=input_text,
        check=False,
    )
    if check and result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        raise OpsError(f"{command[0]} exited with {result.returncode}: {message}")
    return result


def emit(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return

    for key, value in payload.items():
        if isinstance(value, dict | list):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            rendered = str(value)
        print(f"{key}={rendered}")


def required_env(values: dict[str, str], names: list[str]) -> dict[str, str]:
    missing = [name for name in names if not values.get(name)]
    if missing:
        raise OpsError(f"missing required environment keys: {', '.join(missing)}")
    return {name: values[name] for name in names}


def airflow_remote() -> dict[str, str]:
    values = required_env(
        dict(os.environ),
        [
            "AIRFLOW_SSH_HOST",
            "AIRFLOW_SSH_PORT",
            "AIRFLOW_SSH_USER",
            "AIRFLOW_REPOSITORY_PATH",
        ],
    )
    return {
        "host": values["AIRFLOW_SSH_HOST"],
        "port": values["AIRFLOW_SSH_PORT"],
        "username": values["AIRFLOW_SSH_USER"],
        "repository_path": values["AIRFLOW_REPOSITORY_PATH"],
    }


def sender_remote() -> dict[str, str]:
    values = required_env(
        dict(os.environ),
        ["WECHAT_SENDER_SSH_HOST", "WECHAT_SENDER_SSH_PORT", "WECHAT_SENDER_SSH_USER"],
    )
    return {
        "host": values["WECHAT_SENDER_SSH_HOST"],
        "port": values["WECHAT_SENDER_SSH_PORT"],
        "username": values["WECHAT_SENDER_SSH_USER"],
    }


def ssh_command(remote: dict[str, str]) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "PreferredAuthentications=publickey",
        "-o",
        "PasswordAuthentication=no",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "ConnectTimeout=15",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ServerAliveCountMax=20",
        "-p",
        remote["port"],
        f"{remote['username']}@{remote['host']}",
    ]


def docker_compose_command() -> list[str]:
    docker = shutil.which("docker")
    if docker:
        result = subprocess.run(
            [docker, "compose", "version"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return [docker, "compose"]

    legacy = shutil.which("docker-compose")
    if legacy:
        return [legacy]
    raise OpsError("neither 'docker compose' nor 'docker-compose' is available")


def latest_successful_backup(directory: Path) -> Path | None:
    statuses = sorted(directory.glob("airflow-metadata-*.status"), reverse=True)
    for status_path in statuses:
        values = {}
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = value
        if values.get("status") != "success":
            continue
        dump_path = status_path.with_suffix(".dump.enc")
        checksum_path = Path(f"{dump_path}.sha256")
        if dump_path.is_file() and dump_path.stat().st_size > 0 and checksum_path.is_file():
            return dump_path
    return None
