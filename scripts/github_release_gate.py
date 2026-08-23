#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
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


def wait_for_required_check(
    repository: str,
    commit: str,
    token: str,
    name: str,
    *,
    wait_seconds: float,
    poll_seconds: float,
    missing_check_wait_seconds: float = 0,
    fetcher: Callable[[str, str, str], Any] = fetch_check_runs,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, Any], bool, bool]:
    """Wait for an existing required check to finish.

    A queued or in-progress check can legitimately complete later, so it is
    polled until the overall deadline. A missing check is different: it is no
    evidence that the commit ever passed CI. By default it fails immediately;
    callers may opt into a short visibility grace period for a just-created run.
    """
    started_at = monotonic()
    deadline = started_at + wait_seconds
    missing_deadline = started_at + min(wait_seconds, missing_check_wait_seconds)

    while True:
        check = required_check_result(fetcher(repository, commit, token), name)
        now = monotonic()
        if check["status"] == "completed":
            return check, False, False
        if not check["present"] and now >= missing_deadline:
            return check, False, True
        if now >= deadline:
            return check, True, False

        next_deadline = missing_deadline if not check["present"] else deadline
        sleeper(min(poll_seconds, max(0, next_deadline - now)))


def release_payload(
    *,
    target_commit: str,
    required_check: str,
    on_main: bool,
    check: dict[str, Any],
    timed_out: bool,
    missing_check_wait_expired: bool,
) -> dict[str, Any]:
    checks = {
        "target_commit_on_main": on_main,
        "required_check_present": check["present"],
        "required_check_completed": check["status"] == "completed",
        "required_check_successful": check["ok"],
    }
    return {
        "ok": all(checks.values()),
        "target_commit": target_commit,
        "required_check": required_check,
        "check_status": check["status"],
        "check_conclusion": check["conclusion"],
        "timed_out_waiting_for_check": timed_out,
        "missing_check_wait_expired": missing_check_wait_expired,
        "checks": checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an exact GitHub release candidate.")
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--required-check", default="verify")
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=3600,
        help="Maximum time to wait for an existing required check to complete.",
    )
    parser.add_argument(
        "--missing-check-wait-seconds",
        type=float,
        default=0,
        help="Optional short grace period for a required check that is not visible yet.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=10,
        help="Polling interval while the required check is queued or in progress.",
    )
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
    if args.wait_seconds < 0:
        raise OpsError("wait seconds must be non-negative")
    if args.missing_check_wait_seconds < 0:
        raise OpsError("missing check wait seconds must be non-negative")
    if args.poll_seconds <= 0:
        raise OpsError("poll seconds must be positive")

    run(["git", "fetch", "--quiet", "origin", "main"])
    on_main = (
        run(
            ["git", "merge-base", "--is-ancestor", args.target_commit, "origin/main"],
            check=False,
        ).returncode
        == 0
    )

    if on_main:
        check, timed_out, missing_check_wait_expired = wait_for_required_check(
            repository,
            args.target_commit,
            token,
            args.required_check,
            wait_seconds=args.wait_seconds,
            poll_seconds=args.poll_seconds,
            missing_check_wait_seconds=args.missing_check_wait_seconds,
        )
    else:
        check = required_check_result({}, args.required_check)
        timed_out = False
        missing_check_wait_expired = False

    payload = release_payload(
        target_commit=args.target_commit,
        required_check=args.required_check,
        on_main=on_main,
        check=check,
        timed_out=timed_out,
        missing_check_wait_expired=missing_check_wait_expired,
    )
    emit(payload, args.format)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"github-release-gate: {exc}")
        raise SystemExit(1) from exc
