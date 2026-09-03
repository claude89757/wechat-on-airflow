from __future__ import annotations

from unittest.mock import patch

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import webapp_production_health  # noqa: E402


def test_stateless_edge_health_uses_edge_commit_and_accepts_older_host_commit() -> None:
    expected_commit = "a" * 40
    host_commit = "b" * 40
    venues = [
        {
            "id": f"venue-{index}",
            "name": f"Venue {index}",
            "healthy": True,
        }
        for index in range(26)
    ]
    responses = iter(
        [
            (
                200,
                {
                    "ok": True,
                    "runtime": "airflow-host",
                    "deploymentCommit": host_commit,
                    "capabilities": {"priorityWeatherBypass": True},
                },
            ),
            (200, {"venues": venues}),
            (401, {"error": "未授权"}),
            (
                200,
                {
                    "ok": True,
                    "runtime": "cloudflare-stateless-edge",
                    "deploymentCommit": expected_commit,
                    "durableBusinessState": "none",
                    "cutover": True,
                    "quiesced": False,
                    "migrationEndpoint": False,
                },
            ),
        ]
    )

    with patch.object(
        webapp_production_health,
        "request_json",
        side_effect=lambda *_args, **_kwargs: next(responses),
    ):
        result = webapp_production_health.inspect_production(
            base_url="https://example.test",
            expected_commit=expected_commit,
            expected_venue_count=26,
            stateless_edge=True,
        )

    assert result["ok"] is True
    assert result["deployed_commit"] == expected_commit
    assert result["edge_commit"] == expected_commit
    assert result["host_commit"] == host_commit
    assert all(result["checks"].values())
