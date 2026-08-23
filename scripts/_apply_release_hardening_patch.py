#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_exact(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one match in {path}, found {count}")
    target.write_text(text.replace(old, new), encoding="utf-8")


replace_exact(
    "webapp/src/Prototype.tsx",
    'import {\n',
    'import * as DropdownMenu from "@radix-ui/react-dropdown-menu";\nimport {\n',
)
replace_exact(
    "webapp/src/Prototype.tsx",
    "  CourtBasketballIcon,\n",
    "  CourtBasketballIcon,\n  DotsThreeIcon,\n",
)
replace_exact(
    "webapp/src/Prototype.tsx",
    '''            <div className="header-actions">
              <button
                className="coffee-button"
                type="button"
                onClick={() => openPanel("coffee")}
              >
                请作者喝咖啡
              </button>
              <button
                className="icon-button"
''',
    '''            <div className="header-actions">
              <button
                className="coffee-button"
                type="button"
                aria-label="请作者喝咖啡，支持项目维护"
                title="请作者喝咖啡"
                onClick={() => openPanel("coffee")}
              >
                <span aria-hidden="true">☕</span>
                <span>支持作者</span>
              </button>
              <DropdownMenu.Root>
                <DropdownMenu.Trigger asChild>
                  <button
                    className="more-button"
                    type="button"
                    aria-label="更多功能"
                  >
                    <DotsThreeIcon size={22} weight="bold" aria-hidden="true" />
                    <span>更多</span>
                  </button>
                </DropdownMenu.Trigger>
                <DropdownMenu.Portal>
                  <DropdownMenu.Content
                    className="more-menu"
                    align="end"
                    sideOffset={8}
                    collisionPadding={12}
                  >
                    <DropdownMenu.Label className="more-menu-label">更多功能</DropdownMenu.Label>
                    <DropdownMenu.Item
                      className="more-menu-item"
                      onSelect={() => openPanel("subscriptions")}
                    >
                      <ListBulletsIcon size={20} weight="bold" aria-hidden="true" />
                      <span>我的订阅</span>
                    </DropdownMenu.Item>
                    {receipt ? (
                      <DropdownMenu.Item
                        className="more-menu-item"
                        onSelect={() => openPanel("community")}
                      >
                        <UsersThreeIcon size={20} weight="bold" aria-hidden="true" />
                        <span>用户社区</span>
                      </DropdownMenu.Item>
                    ) : null}
                    {receipt && dashboard.identity.isAdmin ? (
                      <DropdownMenu.Item
                        className="more-menu-item"
                        onSelect={() => openPanel("admin")}
                      >
                        <ShieldCheckIcon size={20} weight="bold" aria-hidden="true" />
                        <span>管理后台</span>
                      </DropdownMenu.Item>
                    ) : null}
                    <DropdownMenu.Arrow className="more-menu-arrow" />
                  </DropdownMenu.Content>
                </DropdownMenu.Portal>
              </DropdownMenu.Root>
              <button
                className="icon-button"
''',
)
replace_exact(
    "webapp/src/Prototype.tsx",
    '''          <button
            className="subscriptions-link"
            type="button"
            onClick={() => openPanel("subscriptions")}
          >
            <ListBulletsIcon size={24} weight="bold" />
            <span>我的订阅</span>
            <span aria-hidden="true">›</span>
          </button>

          {receipt ? (
            <button className="subscriptions-link" type="button" onClick={() => openPanel("community")}>
              <UsersThreeIcon size={24} weight="bold" />
              <span>用户社区</span><span aria-hidden="true">›</span>
            </button>
          ) : null}

          {receipt && dashboard.identity.isAdmin ? (
            <button className="subscriptions-link admin-entry" type="button" onClick={() => openPanel("admin")}>
              <ShieldCheckIcon size={24} weight="bold" />
              <span>管理后台</span><span aria-hidden="true">›</span>
            </button>
          ) : null}
''',
    "",
)

(ROOT / "scripts/github_release_gate.py").write_text(
    '''#!/usr/bin/env python3
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
''',
    encoding="utf-8",
)

(ROOT / "tests/github_release_gate_test.py").write_text(
    '''from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import github_release_gate  # noqa: E402


def test_waits_for_in_progress_verify_then_succeeds():
    payloads = iter(
        [
            {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "status": "in_progress",
                        "conclusion": None,
                    }
                ]
            },
            {
                "check_runs": [
                    {
                        "id": 1,
                        "name": "verify",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            },
        ]
    )
    sleeps: list[float] = []
    clock = iter([0.0, 0.0, 1.0])

    check, timed_out, missing_expired = github_release_gate.wait_for_required_check(
        "owner/repo",
        "a" * 40,
        "token",
        "verify",
        wait_seconds=30,
        poll_seconds=5,
        fetcher=lambda *_: next(payloads),
        monotonic=lambda: next(clock),
        sleeper=sleeps.append,
    )

    assert timed_out is False
    assert missing_expired is False
    assert check["ok"] is True
    assert sleeps == [5]


def test_missing_verify_fails_immediately_by_default():
    sleeps: list[float] = []
    clock = iter([0.0, 0.0])

    check, timed_out, missing_expired = github_release_gate.wait_for_required_check(
        "owner/repo",
        "a" * 40,
        "token",
        "verify",
        wait_seconds=1800,
        poll_seconds=10,
        fetcher=lambda *_: {"check_runs": []},
        monotonic=lambda: next(clock),
        sleeper=sleeps.append,
    )

    assert check["present"] is False
    assert timed_out is False
    assert missing_expired is True
    assert sleeps == []


def test_optional_visibility_grace_allows_new_verify_to_appear():
    payloads = iter(
        [
            {"check_runs": []},
            {
                "check_runs": [
                    {
                        "id": 7,
                        "name": "verify",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            },
        ]
    )
    clock = iter([0.0, 0.0, 1.0])

    check, timed_out, missing_expired = github_release_gate.wait_for_required_check(
        "owner/repo",
        "a" * 40,
        "token",
        "verify",
        wait_seconds=30,
        missing_check_wait_seconds=10,
        poll_seconds=5,
        fetcher=lambda *_: next(payloads),
        monotonic=lambda: next(clock),
        sleeper=lambda _: None,
    )

    assert timed_out is False
    assert missing_expired is False
    assert check["present"] is True
    assert check["ok"] is True


def test_terminal_failed_verify_fails_without_sleeping():
    sleeps: list[float] = []
    clock = iter([0.0, 0.0])

    check, timed_out, missing_expired = github_release_gate.wait_for_required_check(
        "owner/repo",
        "a" * 40,
        "token",
        "verify",
        wait_seconds=30,
        poll_seconds=5,
        fetcher=lambda *_: {
            "check_runs": [
                {
                    "id": 2,
                    "name": "verify",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ]
        },
        monotonic=lambda: next(clock),
        sleeper=sleeps.append,
    )

    assert timed_out is False
    assert missing_expired is False
    assert check["ok"] is False
    assert check["conclusion"] == "failure"
    assert sleeps == []


def test_wait_is_bounded_when_existing_verify_never_completes():
    times = iter([0.0, 0.0, 10.0])
    sleeps: list[float] = []

    check, timed_out, missing_expired = github_release_gate.wait_for_required_check(
        "owner/repo",
        "a" * 40,
        "token",
        "verify",
        wait_seconds=10,
        poll_seconds=5,
        fetcher=lambda *_: {
            "check_runs": [
                {
                    "id": 3,
                    "name": "verify",
                    "status": "queued",
                    "conclusion": None,
                }
            ]
        },
        monotonic=lambda: next(times),
        sleeper=sleeps.append,
    )

    assert timed_out is True
    assert missing_expired is False
    assert check["status"] == "queued"
    assert sleeps == [5]
''',
    encoding="utf-8",
)

(ROOT / "scripts/deploy_airflow_transaction.py").write_text(
    '''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

from _ops import OpsError, emit, run

SCRIPTS_DIR = Path(__file__).resolve().parent


def parse_payload(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def command_summary(result: CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "payload": parse_payload(result.stdout or ""),
        "stderr_tail": (result.stderr or "").strip().splitlines()[-1:] or [],
    }


def relay(result: CompletedProcess[str]) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(
            result.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )


def deploy_command(target_commit: str, recover_active_tasks: bool = False) -> list[str]:
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "deploy_airflow.py"),
        "--apply",
        "--target-commit",
        target_commit,
        "--format",
        "json",
    ]
    if recover_active_tasks:
        command.insert(3, "--recover-active-tasks")
    return command


def health_command(expected_commit: str) -> list[str]:
    return [
        sys.executable,
        str(SCRIPTS_DIR / "production_health.py"),
        "--expected-commit",
        expected_commit,
        "--format",
        "json",
    ]


def deploy_with_health(
    target_commit: str,
    *,
    recover_active_tasks: bool = False,
    runner: Callable[..., CompletedProcess[str]] = run,
) -> tuple[dict[str, Any], int]:
    deployment = runner(
        deploy_command(target_commit, recover_active_tasks),
        check=False,
    )
    relay(deployment)
    if deployment.returncode != 0:
        raise OpsError("Airflow deployment failed before the full health gate")

    deployment_payload = parse_payload(deployment.stdout or "")
    previous_commit = (
        deployment_payload.get("remote", {}).get("previous_commit")
        if isinstance(deployment_payload.get("remote"), dict)
        else None
    )
    if not isinstance(previous_commit, str) or len(previous_commit) != 40:
        raise OpsError("Airflow deployment did not return a rollback commit")

    health = runner(health_command(target_commit), check=False)
    relay(health)
    if health.returncode == 0:
        return (
            {
                "ok": True,
                "target_commit": target_commit,
                "previous_commit": previous_commit,
                "deployment": command_summary(deployment),
                "health": command_summary(health),
                "automatic_restore": {"attempted": False, "ok": None},
            },
            0,
        )

    restore = runner(deploy_command(previous_commit), check=False)
    relay(restore)
    restore_health: CompletedProcess[str] | None = None
    if restore.returncode == 0:
        restore_health = runner(health_command(previous_commit), check=False)
        relay(restore_health)

    restore_ok = bool(
        restore.returncode == 0
        and restore_health is not None
        and restore_health.returncode == 0
    )
    return (
        {
            "ok": False,
            "target_commit": target_commit,
            "previous_commit": previous_commit,
            "deployment": command_summary(deployment),
            "health": command_summary(health),
            "automatic_restore": {
                "attempted": True,
                "target_commit": previous_commit,
                "deploy": command_summary(restore),
                "health": command_summary(restore_health) if restore_health else None,
                "ok": restore_ok,
            },
        },
        1,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deploy Airflow, require full health, and automatically restore on failure."
    )
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--recover-active-tasks", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    payload, exit_code = deploy_with_health(
        args.target_commit,
        recover_active_tasks=args.recover_active_tasks,
    )
    emit(payload, args.format)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"deploy-airflow-transaction: {exc}")
        raise SystemExit(1) from exc
''',
    encoding="utf-8",
)

(ROOT / "tests/deploy_airflow_transaction_test.py").write_text(
    '''from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import deploy_airflow_transaction  # noqa: E402


def completed(returncode: int, payload: dict | None = None, stderr: str = ""):
    stdout = f"{json.dumps(payload)}\n" if payload is not None else ""
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def deployment_payload(previous_commit: str) -> dict:
    return {
        "ok": True,
        "remote": {
            "ok": True,
            "applied": True,
            "previous_commit": previous_commit,
        },
    }


def test_successful_health_does_not_restore():
    target = "a" * 40
    previous = "b" * 40
    results = iter([completed(0, deployment_payload(previous)), completed(0, {"ok": True})])
    commands: list[list[str]] = []

    def runner(command, *, check):
        assert check is False
        commands.append(command)
        return next(results)

    payload, exit_code = deploy_airflow_transaction.deploy_with_health(target, runner=runner)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["automatic_restore"] == {"attempted": False, "ok": None}
    assert len(commands) == 2


def test_failed_full_health_restores_previous_commit_and_still_fails_release():
    target = "a" * 40
    previous = "b" * 40
    results = iter(
        [
            completed(0, deployment_payload(previous)),
            completed(1, {"ok": False}, "target unhealthy"),
            completed(0, deployment_payload(target)),
            completed(0, {"ok": True}),
        ]
    )
    commands: list[list[str]] = []

    def runner(command, *, check):
        assert check is False
        commands.append(command)
        return next(results)

    payload, exit_code = deploy_airflow_transaction.deploy_with_health(target, runner=runner)

    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["automatic_restore"]["attempted"] is True
    assert payload["automatic_restore"]["target_commit"] == previous
    assert payload["automatic_restore"]["ok"] is True
    assert previous in commands[2]
    assert previous in commands[3]


def test_failed_restore_is_reported_without_false_success():
    target = "a" * 40
    previous = "b" * 40
    results = iter(
        [
            completed(0, deployment_payload(previous)),
            completed(1, {"ok": False}),
            completed(1, None, "restore failed"),
        ]
    )

    payload, exit_code = deploy_airflow_transaction.deploy_with_health(
        target,
        runner=lambda command, *, check: next(results),
    )

    assert exit_code == 1
    assert payload["automatic_restore"]["attempted"] is True
    assert payload["automatic_restore"]["ok"] is False
    assert payload["automatic_restore"]["health"] is None
''',
    encoding="utf-8",
)

replace_exact(
    ".github/workflows/production-release.yml",
    '''            --required-check verify \\
            --wait-seconds 1800 \\
            --poll-seconds 10 \\
''',
    '''            --required-check verify \\
            --wait-seconds 1800 \\
            --missing-check-wait-seconds 0 \\
            --poll-seconds 10 \\
''',
)
replace_exact(
    ".github/workflows/production-airflow.yml",
    '''            deploy_apply)
              PYTHONPATH=src python scripts/deploy_airflow.py --apply --target-commit "$TARGET_COMMIT" --format json
              PYTHONPATH=src python scripts/production_health.py \\
                --expected-commit "$TARGET_COMMIT" --format json
              ;;
            deploy_recovery)
              PYTHONPATH=src python scripts/deploy_airflow.py --apply --recover-active-tasks \\
                --target-commit "$TARGET_COMMIT" --format json
              PYTHONPATH=src python scripts/production_health.py \\
                --expected-commit "$TARGET_COMMIT" --format json
              ;;
''',
    '''            deploy_apply)
              PYTHONPATH=src python scripts/deploy_airflow_transaction.py \\
                --target-commit "$TARGET_COMMIT" --format json
              ;;
            deploy_recovery)
              PYTHONPATH=src python scripts/deploy_airflow_transaction.py \\
                --recover-active-tasks --target-commit "$TARGET_COMMIT" --format json
              ;;
''',
)
replace_exact(
    ".github/workflows/ci.yml",
    "      - name: Validate active component manifest\n",
    "      - name: Validate active components and runtime drift\n",
)

(ROOT / "tests/release_workflow_contract_test.py").write_text(
    '''from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_gate_fails_fast_when_ci_record_is_missing():
    workflow = (ROOT / ".github/workflows/production-release.yml").read_text(encoding="utf-8")

    assert "--missing-check-wait-seconds 0" in workflow


def test_airflow_apply_uses_transactional_health_and_restore_wrapper():
    workflow = (ROOT / ".github/workflows/production-airflow.yml").read_text(encoding="utf-8")

    assert workflow.count("scripts/deploy_airflow_transaction.py") == 2
    apply_block = workflow.split("deploy_apply)", 1)[1].split("db_cleanup_check)", 1)[0]
    assert "scripts/deploy_airflow.py --apply" not in apply_block


def test_runtime_drift_gate_is_explicit_in_ci():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "Validate active components and runtime drift" in workflow
    assert "scripts/check_active_components.py" in workflow
''',
    encoding="utf-8",
)

(ROOT / "tests/webapp_header_actions_test.py").write_text(
    '''from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_footer_actions_move_into_accessible_header_menu():
    source = (ROOT / "webapp/src/Prototype.tsx").read_text(encoding="utf-8")

    assert 'aria-label="更多功能"' in source
    assert '<DropdownMenu.Root>' in source
    assert 'onSelect={() => openPanel("subscriptions")}' in source
    assert 'onSelect={() => openPanel("community")}' in source
    assert 'onSelect={() => openPanel("admin")}' in source
    assert 'className="subscriptions-link"' not in source


def test_coffee_entry_uses_compact_copy_and_keeps_full_accessible_name():
    source = (ROOT / "webapp/src/Prototype.tsx").read_text(encoding="utf-8")
    main = (ROOT / "webapp/src/main.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "webapp/src/header-menu.css").read_text(encoding="utf-8")

    assert '<span aria-hidden="true">☕</span>' in source
    assert '<span>支持作者</span>' in source
    assert 'aria-label="请作者喝咖啡，支持项目维护"' in source
    assert 'import "./header-menu.css";' in main
    assert ".more-menu-item[data-highlighted]" in styles
''',
    encoding="utf-8",
)

replace_exact(
    "CHANGELOG.md",
    "### Changed\n\n",
    '''### Changed

- Move My Subscriptions, User Community, and Admin into an accessible header
  More menu, and shorten the coffee entry to “☕ 支持作者” while retaining a
  full accessible label and compact narrow-screen behavior.
- Fail the production gate immediately when an older target SHA has no CI check
  record, while continuing to poll checks that are queued or in progress.
- Treat Airflow deploy plus full production health as one transaction: if the
  new containers start but the complete health gate fails, automatically
  restore the pre-deploy SHA, verify the restored version, and fail the release.

''',
)

# Keep the branch clean: the temporary patcher and its one-shot workflow must not
# appear in the final pull request diff.
(ROOT / "scripts/_apply_release_hardening_patch.py").unlink()
(ROOT / ".github/workflows/agent-apply-release-hardening.yml").unlink()
