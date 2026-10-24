from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "host_core_acceptance", ROOT / "scripts/host_core_production.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def report(*failed):
    checks = dict.fromkeys(sorted(MODULE.REQUIRED_ACCEPTANCE_CHECKS), True)
    checks.update(dict.fromkeys(failed, False))
    return dict(
        complete=True,
        schemaVersion=1,
        ok=not failed,
        checks=checks,
        failedChecks=[key for key, value in checks.items() if not value],
        naturalDelivery={},
    )


@pytest.mark.parametrize(
    "failed,expected",
    [
        ((), "accepted"),
        (("naturalEmailProviderDelivered",), "pending"),
        (("naturalWeChatDelivered",), "pending"),
        (("naturalEmailProviderDelivered", "naturalWeChatDelivered"), "pending"),
        (("senderReady",), "failed"),
        (("naturalWeChatDelivered", "allNaturalDagCycles"), "failed"),
        (("unexpectedNewCheck",), "failed"),
    ],
)
def test_classification(failed, expected):
    assert MODULE.acceptance_status(report(*failed)) == expected


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(complete=False),
        lambda r: r.update(schemaVersion=2),
        lambda r: r.update(errors=["unavailable"]),
        lambda r: r.update(error="unavailable"),
        lambda r: r.update(ok=True),
        lambda r: r.update(failedChecks=[]),
        lambda r: r["checks"].pop("senderReady"),
        lambda r: r["checks"].update(senderReady=1),
        lambda r: r["checks"].update(newCheck=None),
    ],
)
def test_unknown_or_inconsistent_report_is_failure(mutation):
    value = report("naturalEmailProviderDelivered")
    mutation(value)
    assert MODULE.acceptance_status(value) == "failed"


@pytest.mark.parametrize(
    "failed,code,status",
    [
        ((), 0, "accepted"),
        (("naturalEmailProviderDelivered",), 75, "pending"),
        (("senderReady",), 1, "failed"),
    ],
)
def test_cli_preserves_non_success_and_report_completeness(failed, code, status, capsys):
    with (
        patch(
            "sys.argv",
            [
                "host_core_production.py",
                "acceptance",
                "--target-commit",
                "a" * 40,
                "--wait-seconds",
                "0",
            ],
        ),
        patch.object(MODULE, "health", return_value=report(*failed)),
    ):
        assert MODULE.main() == code
    result = json.loads(capsys.readouterr().out)
    assert result["acceptanceStatus"] == status
    assert result["success"] is (status == "accepted")
    assert result["complete"] is True


@pytest.mark.parametrize(
    "failed,remote_code,expected",
    [
        ((), 0, "accepted"),
        (("naturalEmailProviderDelivered",), 75, "pending"),
        (("naturalWeChatDelivered",), 1, "failed"),  # unknown remote failure is not pending
        (("senderReady",), 75, "failed"),  # forged exit alone is insufficient
    ],
)
def test_real_shell_exit_and_always_exported_job_output(tmp_path, failed, remote_code, expected):
    source = (ROOT / "scripts/host_core_release.sh").read_text()
    control = source[source.index("changed=false\n") :]
    control = control.replace("/tmp/host-core-", str(tmp_path / "host-core-"))
    value = report(*failed)
    value.update(acceptanceStatus=MODULE.acceptance_status(value), success=not failed)
    payload = tmp_path / "payload"
    payload.write_text(json.dumps(value) + "\n")
    output = tmp_path / "output"
    summary = tmp_path / "summary"
    env = {
        **os.environ,
        "PAYLOAD": str(payload),
        "CODE": str(remote_code),
        "GITHUB_OUTPUT": str(output),
        "EVIDENCE_RESULT": "success",
        "GITHUB_STEP_SUMMARY": str(summary),
    }
    setup = (
        'set -Eeuo pipefail\nOPERATION=acceptance\nremote() { cat "$PAYLOAD"; return "$CODE"; }\n'
    )
    result = subprocess.run(
        ["bash", "-c", setup + control], env=env, capture_output=True, text=True
    )
    assert result.returncode == {"accepted": 0, "pending": 75, "failed": 1}[expected]
    # Execute actual independent always() output step after the failed operation,
    # rather than assuming a failed step itself exposes its outputs.
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-host-core.yml").read_text())
    step = next(
        s for s in workflow["jobs"]["operate"]["steps"] if s.get("id") == "acceptance_status"
    )
    assert step["if"] == "always() && inputs.operation == 'acceptance'"
    exported = subprocess.run(
        ["bash", "-e", "-c", step["run"].replace("/tmp/host-core-", str(tmp_path / "host-core-"))],
        env=env,
        capture_output=True,
        text=True,
    )
    assert exported.returncode == 0
    assert output.read_text() == f"status={expected}\n"
    assert (
        workflow["jobs"]["operate"]["outputs"]["acceptance_status"]
        == "${{ steps.acceptance_status.outputs.status }}"
    )
    trigger = workflow.get("on", workflow.get(True))
    assert (
        trigger["workflow_call"]["outputs"]["acceptance_status"]["value"]
        == "${{ jobs.operate.outputs.acceptance_status }}"
    )


def test_pending_blocks_tag_but_not_healthy_service_and_resume_has_no_mutations():
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-ship.yml").read_text())
    jobs = workflow["jobs"]
    assert (
        "needs.acceptance.outputs.acceptance_status != 'pending'"
        in jobs["safe_pause_on_failure"]["if"]
    )
    assert "needs.acceptance.outputs.acceptance_status == 'accepted'" in jobs["tag"]["if"]
    assert "needs.acceptance.result == 'success'" in jobs["tag"]["if"]
    assert jobs["acceptance"]["with"]["operation"] == "acceptance"
    # GitHub failed-job rerun reruns failed acceptance and dependent record/tag,
    # not successful ancestors (cutover/deploy/activate-workers).
    assert jobs["acceptance"]["needs"] == "natural_cycles"
    assert "acceptance" in jobs["tag"]["needs"]
    record = jobs["record"]["steps"][0]["run"]
    assert "exit 75" in record and 'test "$ACCEPTANCE_STATUS" = accepted' in record


@pytest.mark.parametrize(
    "result,status,pause,tag",
    [
        ("failure", "pending", False, False),
        ("success", "accepted", False, True),
        ("failure", "failed", True, False),
        ("failure", "", True, False),
        ("cancelled", "pending", True, False),
        ("success", "pending", True, False),
        ("success", "", True, False),
    ],
)
def test_actual_workflow_conditions_fail_closed(result, status, pause, tag):
    from types import SimpleNamespace as NS

    workflow = yaml.safe_load((ROOT / ".github/workflows/production-ship.yml").read_text())
    needs = NS(
        host_core_cutover=NS(result="success"),
        deploy=NS(result="success"),
        natural_cycles=NS(result="success"),
        acceptance=NS(result=result, outputs=NS(acceptance_status=status)),
    )
    context = {"needs": needs, "inputs": NS(version="0.8.6", scope="all"), "always": lambda: True}
    for name, expected in (("safe_pause_on_failure", pause), ("tag", tag)):
        expression = workflow["jobs"][name]["if"].replace("&&", "and").replace("||", "or")
        assert eval(expression, {"__builtins__": {}}, context) is expected


def test_acceptance_artifact_preserves_each_rerun_attempt():
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-host-core.yml").read_text())
    artifact = next(
        step
        for step in workflow["jobs"]["operate"]["steps"]
        if step.get("id") == "acceptance_evidence"
    )
    assert "${{ github.run_attempt }}" in artifact["with"]["name"]
    assert artifact["with"].get("overwrite", False) is False


def test_acceptance_and_pause_cannot_checkout_over_newer_runtime():
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-host-core.yml").read_text())
    step = next(
        step for step in workflow["jobs"]["operate"]["steps"] if step.get("id") == "prepare_remote"
    )
    guarded = (
        step["run"].split('if [[ "$operation" == acceptance', 1)[1].split("          else", 1)[0]
    )
    # YAML removes common indentation; split on the actual else boundary.
    guarded = guarded.split("\nelse", 1)[0]
    assert '"$operation" == pause' in guarded
    assert 'test "$previous" = "$target"' in guarded
    assert 'test "$live" = "$target"' in guarded
    assert "git checkout" not in guarded and "git fetch" not in guarded
