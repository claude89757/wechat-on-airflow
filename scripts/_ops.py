from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
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


SSH_BASE_OPTIONS = [
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
]
SSH_CONNECT_ATTEMPTS = 8
# Options that reuse the shared connection while one is open. Scripts run one
# operation at a time, so a module-level list is enough.
_shared_options: list[str] = []


def ssh_options() -> list[str]:
    """Extra ssh/scp options that reuse the shared connection; empty when none is open."""
    return list(_shared_options)


def ssh_command(remote: dict[str, str]) -> list[str]:
    return [
        "ssh",
        *SSH_BASE_OPTIONS,
        *_shared_options,
        "-p",
        remote["port"],
        f"{remote['username']}@{remote['host']}",
    ]


@contextlib.contextmanager
def shared_ssh_connection(
    remote: dict[str, str],
    *,
    attempts: int = SSH_CONNECT_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[None]:
    """Hold one SSH connection for a whole operation; every ssh/scp call reuses it.

    A host whose sshd is being probed with failed logins throttles new connections
    (MaxStartups) and drops some of them, including the one that runs a deployment.
    Opening the connection is the only step that retries, and it runs `true`, so no
    remote command is ever replayed. If the shared connection is lost later, calls
    fall back to ordinary connections.
    """
    if _shared_options:
        yield
        return
    directory = tempfile.mkdtemp(prefix="zs-")
    control = ["-o", f"ControlPath={os.path.join(directory, 'c')}"]
    target = ["-p", remote["port"], f"{remote['username']}@{remote['host']}"]
    probe = [
        "ssh",
        *SSH_BASE_OPTIONS,
        "-o",
        "ControlMaster=auto",
        "-o",
        "ControlPersist=900",
        *control,
        *target,
        "true",
    ]
    connected = False
    try:
        for attempt in range(1, attempts + 1):
            try:
                code = subprocess.run(probe, capture_output=True, check=False).returncode
            except OSError:
                raise OpsError("ssh is unavailable") from None
            if code == 0:
                connected = True
                break
            # 255 means the connection itself failed; anything else is a real answer.
            if code != 255:
                raise OpsError(f"ssh connection check failed with exit code {code}")
            if attempt < attempts:
                sleep(min(3 * attempt, 15))
        if not connected:
            raise OpsError(f"could not open an SSH connection after {attempts} attempts")
        _shared_options[:] = control
        yield
    finally:
        _shared_options.clear()
        if connected:
            subprocess.run(
                ["ssh", "-O", "exit", *SSH_BASE_OPTIONS, *control, *target],
                capture_output=True,
                check=False,
            )
        shutil.rmtree(directory, ignore_errors=True)


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
