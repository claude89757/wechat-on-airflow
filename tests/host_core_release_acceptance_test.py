from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import host_core_release_acceptance as acceptance  # noqa: E402


def cycle_payloads(
    *,
    commit: str,
    observed_at: datetime,
    revision: int,
) -> list[dict[str, object]]:
    venues = [
        {
            "id": f"venue-{index}",
            "lastInspectionAt": (
                observed_at + timedelta(seconds=revision + index)
            ).isoformat(),
        }
        for index in range(26)
    ]
    return [
        {
            "ok": True,
            "runtime": "airflow-host",
            "deploymentCommit": commit,
            "capabilities": {"priorityWeatherBypass": True},
        },
        {"ok": True},
        {
            "ok": True,
            "runtime": "cloudflare-stateless-edge",
            "deploymentCommit": commit,
            "cutover": True,
            "quiesced": False,
            "migrationEndpoint": False,
            "durableBusinessState": "none",
        },
        {"venues": venues},
    ]


def test_validate_cycle_requires_host_edge_and_fresh_venue_state() -> None:
    commit = "a" * 40
    now = datetime.now(UTC)
    health, ready, edge, bootstrap = cycle_payloads(
        commit=commit,
        observed_at=now - timedelta(minutes=2),
        revision=1,
    )

    result = acceptance.validate_cycle(
        health=health,
        ready=ready,
        edge=edge,
        bootstrap=bootstrap,
        expected_commit=commit,
        freshness_minutes=20,
        now=now,
        cycle=1,
    )

    assert result["commit"] == commit
    assert result["venueCount"] == 26
    assert result["freshVenueCount"] == 26


def test_acceptance_observes_three_advancing_natural_cycles() -> None:
    commit = "b" * 40
    now = datetime.now(UTC)
    responses: list[dict[str, object]] = []
    for revision in (1, 2, 3):
        responses.extend(
            cycle_payloads(
                commit=commit,
                observed_at=now - timedelta(minutes=1),
                revision=revision,
            )
        )

    with (
        patch.object(acceptance, "request_json", side_effect=responses),
        patch.object(acceptance.time, "sleep") as sleep,
    ):
        result = acceptance.run_acceptance(
            base_url="https://example.test",
            expected_commit=commit,
            cycles=3,
            interval_seconds=0.01,
            freshness_minutes=20,
        )

    assert result["ok"] is True
    assert result["distinctSnapshotCount"] == 3
    assert result["syntheticNotificationsSent"] is False
    assert sleep.call_count == 2


def test_acceptance_rejects_a_static_observation_snapshot() -> None:
    commit = "c" * 40
    now = datetime.now(UTC)
    responses = cycle_payloads(
        commit=commit,
        observed_at=now - timedelta(minutes=1),
        revision=1,
    ) * 2

    with (
        patch.object(acceptance, "request_json", side_effect=responses),
        patch.object(acceptance.time, "sleep"),
    ):
        try:
            acceptance.run_acceptance(
                base_url="https://example.test",
                expected_commit=commit,
                cycles=2,
                interval_seconds=0,
                freshness_minutes=20,
            )
        except acceptance.AcceptanceError as exc:
            assert "did not advance" in str(exc)
        else:
            raise AssertionError("static natural observation snapshots must fail acceptance")
