#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from _ops import OpsError, emit, run

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def required_check_result(payload: Any, name: str) -> dict[str, Any]:
    runs = payload.get("check_runs", []) if isinstance(payload, dict) else []
    candidates = [
        run
        for run in runs
        if isinstance(run, dict) and run.get("name") == name and isinstance(run.get("id"), int)
    ]
    latest = max(candidates, key=lambda run: int(run["id"]), default=None)
    return {
        "present": latest is not None,
        "status": latest.get("status") if latest else None,
        "conclusion": latest.get("conclusion") if latest else None,
        "ok": bool(
            latest and latest.get("status") == "completed" and latest.get("conclusion") == "success"
        ),
    }


def fetch_check_runs(repository: str, commit: str, token: str) -> Any:
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/commits/{commit}/check-runs?per_page=100",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "wechat-on-airflow-release-gate/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        response = urllib.request.urlopen(request, timeout=20)
    except urllib.error.HTTPError as exc:
        raise OpsError(f"GitHub check-runs API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise OpsError(f"GitHub check-runs API failed: {exc.reason}") from exc
    try:
        return json.loads(response.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpsError("GitHub check-runs API returned invalid JSON") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an exact GitHub release candidate.")
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--required-check", default="verify")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if not COMMIT_PATTERN.fullmatch(args.target_commit):
        raise OpsError("target commit must be a full SHA-1")
    if not REPOSITORY_PATTERN.fullmatch(repository):
        raise OpsError("GITHUB_REPOSITORY must be owner/name")
    if not token:
        raise OpsError("GITHUB_TOKEN is required")

    run(["git", "fetch", "--quiet", "origin", "main"])
    on_main = (
        run(
            ["git", "merge-base", "--is-ancestor", args.target_commit, "origin/main"],
            check=False,
        ).returncode
        == 0
    )
    check = required_check_result(
        fetch_check_runs(repository, args.target_commit, token), args.required_check
    )
    checks = {
        "target_commit_on_main": on_main,
        "required_check_present": check["present"],
        "required_check_completed": check["status"] == "completed",
        "required_check_successful": check["ok"],
    }
    payload = {
        "ok": all(checks.values()),
        "target_commit": args.target_commit,
        "required_check": args.required_check,
        "check_status": check["status"],
        "check_conclusion": check["conclusion"],
        "checks": checks,
    }
    emit(payload, args.format)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"github-release-gate: {exc}")
        raise SystemExit(1) from exc
