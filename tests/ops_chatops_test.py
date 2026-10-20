import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
TARGET = "abcdef0123456789abcdef0123456789abcdef01"
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
        "pull-requests": "write",
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
