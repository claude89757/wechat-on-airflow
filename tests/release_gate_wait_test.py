from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import github_release_gate  # noqa: E402


def test_release_gate_waits_for_running_check() -> None:
    running = {
        "check_runs": [
            {
                "id": 10,
                "name": "verify",
                "status": "in_progress",
                "conclusion": None,
            }
        ]
    }
    ready = {
        "check_runs": [
            {
                "id": 10,
                "name": "verify",
                "status": "completed",
                "conclusion": "success",
            }
        ]
    }
    with (
        patch.object(
            github_release_gate,
            "fetch_check_runs",
            side_effect=[running, ready],
        ) as fetch,
        patch.object(github_release_gate.time, "monotonic", side_effect=[0, 1]),
        patch.object(github_release_gate.time, "sleep") as sleep,
    ):
        result = github_release_gate.wait_for_required_check(
            "owner/repo",
            "a" * 40,
            "token",
            "verify",
            30,
            5,
        )

    assert result["ok"] is True
    assert fetch.call_count == 2
    sleep.assert_called_once_with(5)


def test_release_gate_does_not_wait_after_completed_failure() -> None:
    failed = {
        "check_runs": [
            {
                "id": 10,
                "name": "verify",
                "status": "completed",
                "conclusion": "failure",
            }
        ]
    }
    with (
        patch.object(github_release_gate, "fetch_check_runs", return_value=failed),
        patch.object(github_release_gate.time, "sleep") as sleep,
    ):
        result = github_release_gate.wait_for_required_check(
            "owner/repo",
            "a" * 40,
            "token",
            "verify",
            30,
            5,
        )

    assert result["ok"] is False
    assert result["conclusion"] == "failure"
    sleep.assert_not_called()
