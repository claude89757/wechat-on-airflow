from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import github_release_gate  # noqa: E402


def test_waits_for_in_progress_verify_then_succeeds():
    payloads = iter(
        [
            {"check_runs": [{"id": 1, "name": "verify", "status": "in_progress", "conclusion": None}]},
            {"check_runs": [{"id": 1, "name": "verify", "status": "completed", "conclusion": "success"}]},
        ]
    )
    sleeps: list[float] = []
    clock = iter([0.0, 0.0, 1.0])

    check, timed_out = github_release_gate.wait_for_required_check(
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
    assert check["ok"] is True
    assert sleeps == [5]


def test_waits_when_verify_is_not_visible_yet():
    payloads = iter(
        [
            {"check_runs": []},
            {"check_runs": [{"id": 7, "name": "verify", "status": "completed", "conclusion": "success"}]},
        ]
    )
    clock = iter([0.0, 0.0, 1.0])

    check, timed_out = github_release_gate.wait_for_required_check(
        "owner/repo",
        "a" * 40,
        "token",
        "verify",
        wait_seconds=30,
        poll_seconds=5,
        fetcher=lambda *_: next(payloads),
        monotonic=lambda: next(clock),
        sleeper=lambda _: None,
    )

    assert timed_out is False
    assert check["present"] is True
    assert check["ok"] is True


def test_terminal_failed_verify_fails_without_sleeping():
    sleeps: list[float] = []

    check, timed_out = github_release_gate.wait_for_required_check(
        "owner/repo",
        "a" * 40,
        "token",
        "verify",
        wait_seconds=30,
        poll_seconds=5,
        fetcher=lambda *_: {
            "check_runs": [
                {"id": 2, "name": "verify", "status": "completed", "conclusion": "failure"}
            ]
        },
        monotonic=lambda: 0.0,
        sleeper=sleeps.append,
    )

    assert timed_out is False
    assert check["ok"] is False
    assert check["conclusion"] == "failure"
    assert sleeps == []


def test_wait_is_bounded_when_verify_never_completes():
    times = iter([0.0, 0.0, 10.0])
    sleeps: list[float] = []

    check, timed_out = github_release_gate.wait_for_required_check(
        "owner/repo",
        "a" * 40,
        "token",
        "verify",
        wait_seconds=10,
        poll_seconds=5,
        fetcher=lambda *_: {
            "check_runs": [{"id": 3, "name": "verify", "status": "queued", "conclusion": None}]
        },
        monotonic=lambda: next(times),
        sleeper=sleeps.append,
    )

    assert timed_out is True
    assert check["status"] == "queued"
    assert sleeps == [5]
