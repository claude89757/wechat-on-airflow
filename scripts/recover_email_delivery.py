#!/usr/bin/env python3
"""Invoke the protected, reusable email-only incident recovery procedure."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess

from _ops import REPO_ROOT, OpsError, airflow_remote, emit, ssh_command

SHA = re.compile(r"^[0-9a-f]{40}$")


def remote_program(operation: str, runtime_commit: str) -> str:
    if operation not in {"preflight", "resume", "status"} or not SHA.fullmatch(runtime_commit):
        raise OpsError("an allowed operation and exact runtime commit are required")
    host = (REPO_ROOT / "scripts/email_recovery_host.py").read_text(encoding="utf-8")
    probe = (REPO_ROOT / "scripts/email_recovery_probe.py").read_text(encoding="utf-8")
    options = {"operation": operation, "runtimeCommit": runtime_commit, "probeSource": probe}
    return host + "\nmain(json.loads(" + repr(json.dumps(options)) + "))\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", choices=("preflight", "resume", "status"), required=True)
    parser.add_argument("--operations-commit", required=True)
    parser.add_argument("--expected-runtime-commit", required=True)
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args()
    if not SHA.fullmatch(args.operations_commit) or not SHA.fullmatch(args.expected_runtime_commit):
        raise OpsError("both operations and runtime identities must be exact commits")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise OpsError("recovery runs only through the protected GitHub production workflow")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, check=True, text=True, capture_output=True
    ).stdout.strip()
    if head != args.operations_commit:
        raise OpsError("operations checkout identity mismatch")
    remote = airflow_remote()
    command = ssh_command(remote) + [
        "cd -- " + shlex.quote(remote["repository_path"]) + " && python3 -"
    ]
    result = subprocess.run(
        command,
        input=remote_program(args.operation, args.expected_runtime_commit),
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    reports = []
    for line in result.stdout.splitlines():
        try:
            report = json.loads(line)
        except ValueError:
            continue
        if isinstance(report, dict) and report.get("procedure") == "email-delivery-recovery":
            reports.append(report)
    if not reports:
        raise OpsError("protected recovery returned no bounded report; do not replay automatically")
    for report in reports:
        emit({"operationsCommit": args.operations_commit, **report}, args.format)
    if result.returncode or reports[-1].get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except (OpsError, subprocess.SubprocessError) as exc:
        # SSH/DB output can contain protected values. Keep transport failures bounded.
        print(json.dumps({"ok": False, "errorClass": type(exc).__name__, "replaySafe": False}))
        raise SystemExit(1) from None
