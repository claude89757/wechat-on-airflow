#!/usr/bin/env python3
"""Terminate a wedged Airflow process after repeated local health failures.

Docker's unless-stopped policy restarts a container only after its main process
exits. A single uvicorn worker or triggerer can stay alive while no longer
serving, and the healthcheck then remains unhealthy until someone intervenes.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

FAILURE_LIMIT = 5
CHECK_TIMEOUT_SECONDS = 8


def failure_action(previous: int, healthy: bool, limit: int = FAILURE_LIMIT) -> tuple[int, str]:
    if healthy:
        return 0, "ok"
    count = previous + 1
    if count >= limit:
        return count, "restart"
    return count, "wait"


def read_count(path: Path) -> int:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return 0
    if not raw.isdigit():
        return 0
    return int(raw)


def command_succeeded(command: list[str]) -> bool:
    try:
        completed = subprocess.run(
            command,
            timeout=CHECK_TIMEOUT_SECONDS,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--limit", type=int, default=FAILURE_LIMIT)
    parser.add_argument("--state-dir", default="/tmp")
    parser.add_argument("--pid", type=int, default=1)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = list(args.command)
    if command[:1] == ["--"]:
        command = command[1:]
    safe_name = args.name.replace("-", "")
    if not command or args.limit < 1 or not safe_name.isalnum():
        return 2

    state_path = Path(args.state_dir) / f"airflow-unhealthy-{args.name}"
    count, action = failure_action(
        read_count(state_path),
        command_succeeded(command),
        args.limit,
    )
    if action == "ok":
        state_path.unlink(missing_ok=True)
        return 0
    state_path.write_text(f"{count}\n", encoding="utf-8")
    if action == "restart":
        try:
            os.kill(args.pid, signal.SIGTERM)
        except OSError:
            return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
