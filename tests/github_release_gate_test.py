from __future__ import annotations

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


def test_current_main_head_gets_discovery_grace_but_historical_commit_does_not():
    main_head = "a" * 40
    historical = "b" * 40

    assert (
        github_release_gate.effective_missing_check_wait_seconds(
            target_commit=main_head,
            main_head=main_head,
            missing_check_wait_seconds=0,
            main_head_missing_check_wait_seconds=60,
        )
        == 60
    )
    assert (
        github_release_gate.effective_missing_check_wait_seconds(
            target_commit=historical,
            main_head=main_head,
            missing_check_wait_seconds=0,
            main_head_missing_check_wait_seconds=60,
        )
        == 0
    )


def test_explicit_historical_grace_is_preserved():
    assert (
        github_release_gate.effective_missing_check_wait_seconds(
            target_commit="b" * 40,
            main_head="a" * 40,
            missing_check_wait_seconds=5,
            main_head_missing_check_wait_seconds=60,
        )
        == 5
    )


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
