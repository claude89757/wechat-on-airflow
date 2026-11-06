import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "release_summary", Path(__file__).resolve().parents[1] / "scripts/release_summary.py"
)
SUMMARY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SUMMARY)

ALL_OK = {stage: "success" for stage in SUMMARY.STAGES} | {"activate_retry": "skipped"}


def test_success_has_no_next_step():
    result = SUMMARY.report(ALL_OK, "1", "a" * 40)
    assert result["ok"] and result["failedStage"] is None and result["nextStep"] is None


def test_retried_activation_counts_as_success():
    results = ALL_OK | {"activate": "failure", "activate_retry": "success"}
    assert SUMMARY.report(results, "1", "a" * 40)["ok"]


@pytest.mark.parametrize(
    "stage, phrase",
    [
        ("sender", "still delivering"),
        ("airflow", "still delivering"),
        ("host_core", "may be paused"),
    ],
)
def test_failure_states_its_effect_and_how_to_resume(stage, phrase):
    result = SUMMARY.report(ALL_OK | {stage: "failure"}, "42", "a" * 40)
    assert result["failedStage"] == stage
    assert phrase in result["effect"]
    assert "make release-resume RUN_ID=42" in result["nextStep"]


def test_failed_activation_retry_reports_paused_delivery():
    results = ALL_OK | {"activate": "failure", "activate_retry": "failure"}
    result = SUMMARY.report(results, "1", "a" * 40)
    assert result["failedStage"] == "activate"
    assert "paused" in result["effect"]
