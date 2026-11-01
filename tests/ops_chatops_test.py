import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
TARGET = "abcdef0123456789abcdef0123456789abcdef01"
RUNTIME = "0123456789abcdef0123456789abcdef01234567"
READ_ONLY_COMMANDS = (
    ("airflow-health", "airflow_health", "health"),
    ("crland-inspection-diagnose", "crland_inspection_diagnose", "crland_inspection_diagnose"),
)


def load_workflow(name):
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def parse_command(tmp_path, body):
    workflow = load_workflow("ops-chatops.yml")
    step = next(step for step in workflow["jobs"]["route"]["steps"] if step.get("id") == "command")
    lines = step["run"].splitlines()
    assert lines[0] == "python - <<'PY'"
    assert lines[-1] == "PY"
    output_path = tmp_path / "github-output"
    result = subprocess.run(
        [sys.executable, "-c", "\n".join(lines[1:-1])],
        env={"BODY": body, "GITHUB_OUTPUT": str(output_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    outputs = {}
    if output_path.exists():
        outputs = dict(line.split("=", 1) for line in output_path.read_text().splitlines())
    return result, outputs


@pytest.mark.parametrize(("command", "action", "operation"), READ_ONLY_COMMANDS)
@pytest.mark.parametrize("target", [TARGET, TARGET.upper()])
def test_read_only_commands_accept_and_normalize_full_sha(
    tmp_path, command, action, operation, target
):
    result, outputs = parse_command(tmp_path, f"/ops {command} {target}")

    assert result.returncode == 0, result.stderr
    assert outputs["action"] == action
    assert outputs["target_commit"] == TARGET
    assert outputs["include_sender"] == "false"
    assert outputs["scope"] == "auto"
    assert outputs["target_selector"] == "all"


@pytest.mark.parametrize(("command", "action", "operation"), READ_ONLY_COMMANDS)
@pytest.mark.parametrize("target", ["", "a" * 39, "a" * 41, "g" * 40, "HEAD", "refs/heads/main"])
def test_read_only_commands_reject_missing_or_invalid_sha(
    tmp_path, command, action, operation, target
):
    result, outputs = parse_command(tmp_path, f"/ops {command} {target}")

    assert result.returncode != 0
    assert outputs == {}


@pytest.mark.parametrize(("command", "action", "operation"), READ_ONLY_COMMANDS)
@pytest.mark.parametrize(
    "extra", ["sender=true", "scope=all", "--apply", "\n/release apply " + TARGET]
)
def test_read_only_commands_reject_additional_operations(
    tmp_path, command, action, operation, extra
):
    result, outputs = parse_command(tmp_path, f"/ops {command} {TARGET} {extra}")

    assert result.returncode != 0
    assert outputs == {}


@pytest.mark.parametrize(
    ("body", "action", "mode"),
    [
        (f"/release preflight {TARGET} scope=auto sender=false", "release", "preflight"),
        (f"/release apply {TARGET} scope=airflow sender=false", "release", "apply"),
        (f"/release ship 0.8.5 {TARGET} scope=auto sender=false", "ship", ""),
        (f"/release tag 0.8.5 {TARGET}", "tag", ""),
    ],
)
def test_existing_release_commands_keep_their_routes(tmp_path, body, action, mode):
    result, outputs = parse_command(tmp_path, body)

    assert result.returncode == 0, result.stderr
    assert outputs["action"] == action
    assert outputs["mode"] == mode
    assert outputs["target_commit"] == TARGET
    assert outputs["recovery_runtime_commit"] == ""
    assert outputs["recovery_delivery_enabled"] == "false"


def test_recovery_route_requires_recorded_runtime_and_control_timestamp(tmp_path):
    timestamp = "2026-11-01T02:55:08.601801+00:00"
    result, outputs = parse_command(
        tmp_path,
        f"/release recover 0.9.1 {TARGET.upper()} {RUNTIME.upper()} {timestamp} scope=all sender=true",
    )
    assert result.returncode == 0, result.stderr
    assert outputs["action"] == "ship"
    assert outputs["mode"] == "recovery"
    assert outputs["target_commit"] == TARGET
    assert outputs["recovery_runtime_commit"] == RUNTIME
    assert outputs["recovery_control_updated_at"] == timestamp
    assert outputs["recovery_delivery_enabled"] == "true"
    assert outputs["recovery_wechat_enabled"] == "false"
    assert outputs["include_sender"] == "true"
    route = load_workflow("ops-chatops.yml")["jobs"]["ship"]
    assert route["uses"] == "./.github/workflows/production-ship.yml"
    for field in ("recovery_runtime_commit", "recovery_control_updated_at"):
        assert route["with"][field] == "${{ needs.route.outputs." + field + " }}"


@pytest.mark.parametrize(
    "body",
    [
        f"/release recover 0.9.1 {TARGET} {RUNTIME} scope=all sender=true",
        f"/release recover 0.9.1 {TARGET} {RUNTIME} 2026-11-01 scope=all sender=true",
        f"/release recover 0.9.1 {TARGET} {RUNTIME} 2026-02-31T02:55:08Z scope=all sender=true",
        f"/release recover 0.9.1 {TARGET} {RUNTIME} 2026-11-01T10:55:08+08:00 scope=all sender=true",
        f"/release recover 0.9.1 {TARGET} {RUNTIME} 2026-11-01T02:55:08Z scope=auto sender=true",
        f"/release recover 0.9.1 {TARGET} {RUNTIME} 2026-11-01T02:55:08Z scope=all sender=false",
        f"/release recover 0.9.1 {TARGET} {TARGET} 2026-11-01T02:55:08Z scope=all sender=true",
        f"/release recover 0.7.0 {TARGET} {RUNTIME} 2026-11-01T02:55:08Z scope=all sender=true",
        f"/release recover 0.9.1 {TARGET} main 2026-11-01T02:55:08Z scope=all sender=true",
        f"/release recover 0.9.1 {TARGET} {RUNTIME} 2026-11-01T02:55:08Z scope=all sender=true force=true",
    ],
)
def test_recovery_route_rejects_missing_fences_and_unsafe_scope(tmp_path, body):
    result, outputs = parse_command(tmp_path, body)
    assert result.returncode != 0
    assert outputs == {}


def test_recovery_ship_preserves_full_deployment_and_acceptance_dependencies():
    workflow = load_workflow("production-ship.yml")
    jobs = workflow["jobs"]
    contract = jobs["contract"]["steps"][-1]
    assert "--recovery-runtime-commit" in contract["run"]
    assert "--recovery-control-updated-at" in contract["run"]
    assert jobs["host_core_cutover"]["needs"] == "preflight"
    assert "'recovery-upgrade'" in jobs["host_core_cutover"]["with"]["operation"]
    for field in (
        "recovery_runtime_commit",
        "recovery_control_updated_at",
        "recovery_delivery_enabled",
        "recovery_wechat_enabled",
    ):
        assert jobs["host_core_cutover"]["with"][field] == "${{ inputs." + field + " }}"
    assert jobs["natural_cycles"]["needs"] == "deploy"
    assert jobs["natural_cycles"]["with"]["operation"] == "activate-workers"
    assert jobs["acceptance"]["needs"] == "natural_cycles"
    assert jobs["acceptance"]["with"]["operation"] == "acceptance"
    assert "acceptance" in jobs["safe_pause_on_failure"]["needs"]
    assert "needs.acceptance.outputs.acceptance_status == 'accepted'" in jobs["tag"]["if"]


@pytest.mark.parametrize("operation", ["preflight", "apply", "health", "inspect"])
def test_pi_ydmap_commands_route_exact_operation_to_protected_workflow(tmp_path, operation):
    result, outputs = parse_command(tmp_path, f"/ops pi-ydmap-{operation} {TARGET.upper()}")

    assert result.returncode == 0, result.stderr
    assert outputs["action"] == "pi_ydmap"
    assert outputs["mode"] == operation
    assert outputs["target_commit"] == TARGET
    assert outputs["include_sender"] == "false"
    jobs = load_workflow("ops-chatops.yml")["jobs"]
    route = jobs["pi_ydmap"]
    assert route["uses"] == "./.github/workflows/production-pi-ydmap.yml"
    assert route["if"] == "needs.route.outputs.action == 'pi_ydmap'"
    assert route["with"] == {
        "operation": "${{ needs.route.outputs.mode }}",
        "target_commit": "${{ needs.route.outputs.target_commit }}",
        "request_id": "ops-${{ github.run_id }}",
    }
    assert route["secrets"] == "inherit"
    assert "pi_ydmap" in jobs["report"]["needs"]


@pytest.mark.parametrize(
    "body",
    [
        "/ops pi-ydmap-apply HEAD",
        "/ops pi-ydmap-inspect",
        f"/ops pi-ydmap-apply {TARGET} legacy_drain_confirmed=true",
        f"/ops pi-ydmap-preflight {TARGET}\n/release apply {TARGET}",
        f"/ops pi-ydmap-exec {TARGET}",
    ],
)
def test_pi_ydmap_commands_reject_ref_aliases_bypass_flags_and_extra_operations(tmp_path, body):
    result, outputs = parse_command(tmp_path, body)

    assert result.returncode != 0
    assert outputs == {}


def test_release_command_accepts_explicit_pi_ydmap_scope(tmp_path):
    result, outputs = parse_command(tmp_path, f"/release preflight {TARGET} scope=pi_ydmap")

    assert result.returncode == 0, result.stderr
    assert outputs["scope"] == "pi_ydmap"


def test_read_only_routes_keep_owner_issue_and_protected_workflow_boundaries():
    workflow = load_workflow("ops-chatops.yml")
    jobs = workflow["jobs"]
    guard = jobs["route"]["if"]

    assert "github.event.comment.user.login == github.repository_owner &&" in guard
    assert "github.event.issue.number == 39 &&" in guard
    assert "startsWith(github.event.comment.body, '/ops ')" in guard
    assert workflow["permissions"] == {
        "checks": "read",
        "contents": "write",
        "issues": "write",
    }
    for _, action, operation in READ_ONLY_COMMANDS:
        job = jobs[action]
        assert job["if"] == f"needs.route.outputs.action == '{action}'"
        assert job["needs"] == "route"
        assert job["uses"] == "./.github/workflows/production-airflow.yml"
        assert job["with"] == {
            "operation": operation,
            "target_commit": "${{ needs.route.outputs.target_commit }}",
            "request_id": "ops-${{ github.run_id }}",
            "confirm_real_send": "false",
            "probe_target_membership": "all",
        }
        assert action in jobs["report"]["needs"]


def test_read_only_operations_keep_production_environment_and_exact_main_commit_checks():
    workflow = load_workflow("production-airflow.yml")
    job = workflow["jobs"]["operate"]
    steps = {step.get("name"): step for step in job["steps"] if "name" in step}

    assert job["environment"] == "production"
    assert workflow["permissions"] == {"checks": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "production-airflow-v2",
        "cancel-in-progress": "false",
    }
    validation = steps["Validate exact target"]["run"]
    assert 'test "$(git rev-parse HEAD)" = "$TARGET_COMMIT"' in validation
    assert 'git merge-base --is-ancestor "$TARGET_COMMIT" origin/main' in validation
    operations = workflow["on"]["workflow_dispatch"]["inputs"]["operation"]["options"]
    source = steps["Execute protected operation"]["run"]
    for _, _, operation in READ_ONLY_COMMANDS:
        assert operation in operations
        block = source.split(f"{operation})", 1)[1].split(";;", 1)[0]
        assert '--expected-commit "$TARGET_COMMIT" --format json' in block
        assert "--apply" not in block
        assert "--confirm-real-send" not in block
    assert "PYTHONPATH=src python scripts/production_health.py" in source
    assert "PYTHONPATH=scripts python scripts/diagnose_crland_inspections.py" in source


@pytest.mark.parametrize("operation", ["preflight", "resume", "status"])
def test_email_recovery_routes_two_distinct_exact_commits(tmp_path, operation):
    result, outputs = parse_command(
        tmp_path, f"/ops email-{operation} {TARGET.upper()} {RUNTIME.upper()}"
    )

    assert result.returncode == 0, result.stderr
    assert outputs["action"] == "email_recovery"
    assert outputs["mode"] == operation
    assert outputs["target_commit"] == TARGET
    assert outputs["runtime_commit"] == RUNTIME
    assert outputs["include_sender"] == "false"
    jobs = load_workflow("ops-chatops.yml")["jobs"]
    route = jobs["email_recovery"]
    assert route["if"] == "needs.route.outputs.action == 'email_recovery'"
    assert route["needs"] == "route"
    assert route["uses"] == "./.github/workflows/production-email-recovery.yml"
    assert route["with"] == {
        "operation": "${{ needs.route.outputs.mode }}",
        "operations_commit": "${{ needs.route.outputs.target_commit }}",
        "expected_runtime_commit": "${{ needs.route.outputs.runtime_commit }}",
    }
    assert route["secrets"] == "inherit"
    assert "email_recovery" in jobs["report"]["needs"]
    report = jobs["report"]["steps"][0]
    assert report["env"]["EMAIL_RECOVERY_RESULT"] == "${{ needs.email_recovery.result }}"
    assert report["env"]["RUNTIME_COMMIT"] == "${{ needs.route.outputs.runtime_commit }}"
    assert 'label="email $MODE (existing runtime $RUNTIME_COMMIT)"' in report["run"]


@pytest.mark.parametrize(
    "body",
    [
        "/ops email-resume",
        f"/ops email-resume {TARGET}",
        f"/ops email-resume HEAD {RUNTIME}",
        f"/ops email-preflight {TARGET} main",
        f"/ops email-status {TARGET} {'f' * 39}",
        f"/ops email-resume {TARGET} {RUNTIME} --force",
        f"/ops email-resume {TARGET} {RUNTIME} sender=true",
        f"/ops email-resume {TARGET} {RUNTIME}\n/release apply {TARGET}",
        f"/ops email-exec {TARGET} {RUNTIME}",
    ],
)
def test_email_recovery_rejects_aliases_missing_identity_and_extra_actions(tmp_path, body):
    result, outputs = parse_command(tmp_path, body)

    assert result.returncode != 0
    assert outputs == {}


def test_email_recovery_requires_owner_environment_ci_and_existing_runtime_identity():
    workflow = load_workflow("production-email-recovery.yml")
    assert workflow["permissions"] == {"checks": "read", "contents": "read"}
    assert workflow["concurrency"] == {
        "group": "production-host-core",
        "cancel-in-progress": "false",
    }
    assert set(workflow["on"]) == {"workflow_call", "workflow_dispatch"}
    for trigger in workflow["on"].values():
        assert set(trigger["inputs"]) == {
            "operation",
            "operations_commit",
            "expected_runtime_commit",
        }
        assert all(value["required"] == "true" for value in trigger["inputs"].values())

    job = workflow["jobs"]["recover"]
    assert job["environment"] == "production"
    guard = job["if"]
    assert "github.event.issue.number == 39 &&" in guard
    assert "github.event.comment.user.login == github.repository_owner" in guard
    assert "github.event_name == 'workflow_dispatch' &&" in guard
    assert "github.actor == github.repository_owner" in guard
    assert set(job["env"]) == {
        "OPERATION",
        "OPERATIONS_COMMIT",
        "RUNTIME_COMMIT",
        "AIRFLOW_SSH_HOST",
        "AIRFLOW_SSH_PORT",
        "AIRFLOW_SSH_USER",
        "AIRFLOW_REPOSITORY_PATH",
    }
    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    names = list(steps)
    ci = steps["Require successful CI for both exact commits"]["run"]
    assert 'for commit in "$OPERATIONS_COMMIT" "$RUNTIME_COMMIT"; do' in ci
    assert '--target-commit "$commit"' in ci
    assert "--required-check verify" in ci
    assert "--missing-check-wait-seconds 0" in ci
    assert names.index("Require successful CI for both exact commits") < names.index(
        "Configure production SSH identity"
    )
    execute = steps["Execute protected email operation"]["run"]
    assert 'test "$(git rev-parse origin/main)" = "$OPERATIONS_COMMIT"' in execute
    assert '--operation "$OPERATION"' in execute
    assert '--operations-commit "$OPERATIONS_COMMIT"' in execute
    assert '--expected-runtime-commit "$RUNTIME_COMMIT"' in execute
    status = steps["Record independent post-resume status"]
    assert status["if"] == "inputs.operation == 'resume' && steps.recovery.outcome == 'success'"
    assert "--operation status" in status["run"]
    assert "--confirm-real-send" not in execute + status["run"]
    assert "activate-workers" not in execute + status["run"]
    artifacts = steps["Publish bounded recovery evidence"]["with"]
    assert artifacts["path"].splitlines() == [
        "/tmp/email-recovery.json",
        "/tmp/email-recovery-status.json",
    ]


@pytest.mark.parametrize("scenario", ["valid", "stale_operations", "unrelated_runtime"])
def test_email_recovery_commit_validation_rejects_drift_before_ssh(tmp_path, scenario):
    """Exercise the workflow's actual shell gate against isolated Git histories."""
    git = shutil.which("git")
    assert git
    repository = tmp_path / "repository"
    repository.mkdir()

    def git_run(*arguments):
        return subprocess.run(
            [git, *arguments],
            cwd=repository,
            check=True,
            text=True,
            capture_output=True,
            timeout=10,
        ).stdout.strip()

    git_run("init", "--quiet")
    git_run("config", "user.name", "Workflow guard test")
    git_run("config", "user.email", "workflow-test@example.invalid")
    git_run("commit", "--allow-empty", "--quiet", "-m", "existing runtime")
    runtime = git_run("rev-parse", "HEAD")
    git_run("commit", "--allow-empty", "--quiet", "-m", "verified operations")
    operations = git_run("rev-parse", "HEAD")
    git_run("update-ref", "refs/remotes/origin/main", operations)
    if scenario == "stale_operations":
        operations = runtime
        git_run("checkout", "--quiet", "--detach", operations)
    elif scenario == "unrelated_runtime":
        git_run("checkout", "--quiet", "--orphan", "unrelated")
        git_run("commit", "--allow-empty", "--quiet", "-m", "unrelated runtime")
        runtime = git_run("rev-parse", "HEAD")
        git_run("checkout", "--quiet", "--detach", operations)

    # Network fetch alone is replaced; all identity/ancestry checks use real Git.
    binaries = tmp_path / "bin"
    binaries.mkdir()
    shim = binaries / "git"
    shim.write_text(
        f'#!/bin/sh\nif [ "$1" = fetch ]; then exit 0; fi\nexec {shlex.quote(git)} "$@"\n'
    )
    shim.chmod(0o755)
    workflow = load_workflow("production-email-recovery.yml")
    step = next(
        item
        for item in workflow["jobs"]["recover"]["steps"]
        if item.get("name") == "Validate exact operations and existing-runtime commits"
    )
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        cwd=repository,
        env={
            **os.environ,
            "PATH": str(binaries) + os.pathsep + os.environ.get("PATH", ""),
            "OPERATION": "resume",
            "OPERATIONS_COMMIT": operations,
            "RUNTIME_COMMIT": runtime,
        },
        check=False,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert (result.returncode == 0) == (scenario == "valid"), result.stderr
