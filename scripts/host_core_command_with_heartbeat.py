#!/usr/bin/env python3
"""Run one Host Core production command with periodic progress heartbeats.

The production host still uses Python 3.6, so this wrapper intentionally avoids
newer syntax.  It keeps the SSH session active while the child command captures
a long-running D1 SQL import, then forwards the child's exact output and exit
status.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_CORE_SCRIPT = ROOT / "scripts" / "host_core_production.py"


def run_with_heartbeat(command, label, interval_seconds=20):
    if interval_seconds <= 0:
        raise ValueError("heartbeat interval must be positive")

    started_at = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=str(ROOT),
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        while True:
            try:
                stdout, stderr = process.communicate(timeout=interval_seconds)
                break
            except subprocess.TimeoutExpired:
                print(
                    json.dumps(
                        {
                            "elapsedSeconds": int(time.monotonic() - started_at),
                            "event": "host_core_command_heartbeat",
                            "label": label,
                        },
                        sort_keys=True,
                    ),
                    file=sys.stderr,
                )
                sys.stderr.flush()
    except BaseException:
        process.kill()
        stdout, stderr = process.communicate()
        if stdout:
            sys.stdout.write(stdout)
            sys.stdout.flush()
        if stderr:
            sys.stderr.write(stderr)
            sys.stderr.flush()
        raise

    if stdout:
        sys.stdout.write(stdout)
        sys.stdout.flush()
    if stderr:
        sys.stderr.write(stderr)
        sys.stderr.flush()
    return process.returncode


def main(arguments=None):
    values = list(sys.argv[1:] if arguments is None else arguments)
    if not values:
        print("host-core command is required", file=sys.stderr)
        return 2
    command = [sys.executable, str(HOST_CORE_SCRIPT)] + values
    return run_with_heartbeat(command, f"Host Core {values[0]}")


if __name__ == "__main__":
    sys.exit(main())
