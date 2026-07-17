from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


class OpsError(RuntimeError):
    pass


def load_env(path: Path | None = None) -> dict[str, str]:
    env_path = path or REPO_ROOT / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value and value[0] in {"'", '"'}:
            try:
                parsed = shlex.split(value)
            except ValueError as exc:
                raise OpsError(f"invalid quoted value for {key} in {env_path}") from exc
            value = parsed[0] if parsed else ""
        values[key] = value
    return values


def merged_env(path: Path | None = None) -> dict[str, str]:
    values = load_env(path)
    values.update(os.environ)
    return values


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
