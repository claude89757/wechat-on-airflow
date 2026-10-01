"""Sender apply must follow the exact-target Host Core preparation in Ship."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"
GUARD_NAME = "Require coordinated Host Core release"


def workflow(name):
    # BaseLoader preserves the Actions `on` key instead of treating it as True.
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def guard_step(name, job):
    return next(
        step for step in workflow(name)["jobs"][job]["steps"] if step.get("name") == GUARD_NAME
    )


def run_guard(name, job, *, inputs, event_name="workflow_dispatch", sender_planned="true"):
    step = guard_step(name, job)
    assert "if" not in step
    env = {"PATH": os.environ["PATH"], "GITHUB_EVENT_NAME": event_name}
    for key, expression in step["env"].items():
        if expression == "${{ steps.plan.outputs.deploy_sender }}":
            env[key] = sender_planned
        else:
            assert expression.startswith("${{ inputs.") and expression.endswith(" }}")
            env[key] = inputs.get(expression[len("${{ inputs.") : -len(" }}")], "")
    return subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize("prepared", ["", "false"])
def test_direct_sender_apply_is_rejected_before_deployment(prepared):
    result = run_guard(
        "production-wechat-sender.yml",
        "operate",
        inputs={"operation": "apply", "host_core_prepared": prepared},
    )
    assert result.returncode == 2
    assert "Production Ship" in result.stderr


@pytest.mark.parametrize("event_name", ["workflow_dispatch", "issue_comment"])
def test_coordinated_reusable_apply_keeps_the_original_callers_event(event_name):
    # GitHub retains the caller's event, including in nested reusable workflows;
    # it does not replace it with `workflow_call`.
    for name, job, inputs in (
        (
            "production-release.yml",
            "gate",
            {
                "mode": "apply",
                "scope": "all",
                "include_sender": "true",
                "host_core_prepared": "true",
            },
        ),
        (
            "production-wechat-sender.yml",
            "operate",
            {"operation": "apply", "host_core_prepared": "true"},
        ),
    ):
        result = run_guard(name, job, inputs=inputs, event_name=event_name)
        assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("event_name", ["workflow_dispatch", "issue_comment"])
@pytest.mark.parametrize(
    ("prepared", "scope", "include_sender"),
    [
        ("", "all", "true"),
        ("false", "all", "true"),
        ("true", "sender", "true"),
        ("true", "auto", "true"),
        ("true", "all", "false"),
    ],
)
def test_release_apply_cannot_bypass_ship_preparation(event_name, prepared, scope, include_sender):
    result = run_guard(
        "production-release.yml",
        "gate",
        inputs={
            "mode": "apply",
            "scope": scope,
            "include_sender": include_sender,
            "host_core_prepared": prepared,
        },
        event_name=event_name,
    )
    assert result.returncode == 2
    assert "Production Ship" in result.stderr


@pytest.mark.parametrize(
    "operation",
    ["health", "device_diagnose", "ui_screenshot", "device_recover", "dry_run"],
)
def test_standalone_non_apply_sender_operations_remain_available(operation):
    result = run_guard("production-wechat-sender.yml", "operate", inputs={"operation": operation})
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("mode", "sender_planned"), [("preflight", "true"), ("apply", "false")])
def test_preflight_and_independent_components_do_not_need_ship(mode, sender_planned):
    result = run_guard(
        "production-release.yml",
        "gate",
        inputs={"mode": mode, "scope": "all", "include_sender": "true"},
        sender_planned=sender_planned,
    )
    assert result.returncode == 0, result.stderr


def test_preparation_proof_is_only_passed_by_exact_target_ship_chain():
    ship = workflow("production-ship.yml")["jobs"]
    release = workflow("production-release.yml")
    sender = workflow("production-wechat-sender.yml")
    for called in (release, sender):
        proof = called["on"]["workflow_call"]["inputs"]["host_core_prepared"]
        assert proof["type"] == "boolean"
        assert proof["default"] == "false"
        assert "host_core_prepared" not in called["on"]["workflow_dispatch"]["inputs"]

    prepare = ship["host_core_cutover"]
    assert prepare["uses"] == "./.github/workflows/production-host-core.yml"
    assert prepare["with"]["operation"] == "full-cutover"
    assert prepare["with"]["target_commit"] == "${{ inputs.target_commit }}"
    assert "host_core_cutover" in ship["deploy"]["needs"]
    assert ship["deploy"]["with"]["host_core_prepared"] == (
        "${{ needs.host_core_cutover.result == 'success' }}"
    )
    for call in (ship["deploy"], release["jobs"]["sender"]):
        assert call["with"]["target_commit"] == "${{ inputs.target_commit }}"
    assert release["jobs"]["sender"]["with"]["host_core_prepared"] == (
        "${{ inputs.host_core_prepared == true }}"
    )
    for component in ("webapp", "airflow", "sender"):
        assert "gate" in release["jobs"][component]["needs"]


def test_every_known_release_caller_preserves_the_preparation_boundary():
    callers = {}
    for path in WORKFLOWS.glob("*.yml"):
        for job_name, job in workflow(path.name)["jobs"].items():
            if job.get("uses") in {
                "./.github/workflows/production-release.yml",
                "./.github/workflows/production-wechat-sender.yml",
            }:
                callers[(path.name, job_name)] = job["with"].get("host_core_prepared")
    assert callers == {
        ("ops-chatops.yml", "release"): None,
        ("production-ship.yml", "deploy"): "${{ needs.host_core_cutover.result == 'success' }}",
        ("production-release.yml", "sender"): "${{ inputs.host_core_prepared == true }}",
    }


def test_guards_run_before_remote_access_and_release_components():
    sender_steps = workflow("production-wechat-sender.yml")["jobs"]["operate"]["steps"]
    assert sender_steps[0]["name"] == GUARD_NAME
    release_steps = workflow("production-release.yml")["jobs"]["gate"]["steps"]
    names = [step.get("name") for step in release_steps]
    assert names.index("Plan component-scoped release") < names.index(GUARD_NAME)
    assert names.index(GUARD_NAME) < names.index("Require exact main commit and successful CI")
