from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

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
        for index in range(27)
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
            (404, {"error": "未找到"}),
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
            expected_venue_count=27,
            stateless_edge=True,
        )

    assert result["ok"] is True
    assert result["deployed_commit"] == expected_commit
    assert result["edge_commit"] == expected_commit
    assert result["host_commit"] == host_commit
    assert all(result["checks"].values())


def test_health_checks_both_domains_and_fails_if_legacy_domain_fails(capsys) -> None:
    import json

    expected = "a" * 40
    with (
        patch.object(sys, "argv", ["health", "--expected-commit", expected, "--format", "json"]),
        patch.object(
            webapp_production_health,
            "wait_for_production",
            side_effect=[{"ok": True}, {"ok": False}],
        ) as inspect,
    ):
        import pytest

        with pytest.raises(SystemExit, match="1"):
            webapp_production_health.main()
    assert [call.kwargs["base_url"] for call in inspect.call_args_list] == [
        "https://courts.zacks.vision",
        "https://zacks.claude89757.cc",
    ]
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert len(report["domains"]) == 2


def test_public_domain_contract_matches_worker_routes() -> None:
    import json

    import yaml

    root = SCRIPTS.parent
    target = yaml.safe_load((root / "config/runtime-target.yaml").read_text())["managed_services"][
        "webapp"
    ]
    worker = json.loads((root / "webapp/wrangler.jsonc").read_text())
    assert target["public_base_url"] == "https://" + target["public_hostname"]
    assert [target["public_base_url"], *target["additional_public_base_urls"]] == [
        "https://" + route["pattern"] for route in worker["routes"] if route["custom_domain"]
    ]
    assert worker["name"] == "zacks-tennis-alerts"
    assert not worker.get("d1_databases")
    assert not worker["triggers"]["crons"]


def test_new_domain_transport_propagation_is_retried_without_deploying() -> None:
    with (
        patch.object(
            webapp_production_health,
            "inspect_production",
            side_effect=[webapp_production_health.OpsError("DNS not ready"), {"ok": True}],
        ) as inspect,
        patch.object(webapp_production_health.time, "sleep"),
    ):
        result = webapp_production_health.wait_for_production(
            base_url="https://courts.zacks.vision",
            expected_commit="a" * 40,
            expected_venue_count=26,
            propagation_timeout_seconds=10,
            retry_interval_seconds=1,
            stateless_edge=True,
        )
    assert result["ok"] is True
    assert inspect.call_count == 2


def test_failed_new_domain_does_not_skip_legacy_domain(capsys) -> None:
    import json

    import pytest

    with (
        patch.object(sys, "argv", ["health", "--expected-commit", "a" * 40, "--format", "json"]),
        patch.object(
            webapp_production_health,
            "wait_for_production",
            side_effect=[webapp_production_health.OpsError("TLS not ready"), {"ok": True}],
        ),
        pytest.raises(SystemExit, match="1"),
    ):
        webapp_production_health.main()
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["domains"][1]["ok"] is True
