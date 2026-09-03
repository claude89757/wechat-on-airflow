from __future__ import annotations

from unittest.mock import patch

from wechat_airflow.host_core import api
from wechat_airflow.host_core.settings import HostCoreSettings


def settings(*, observation_mode: str, owner: str, gate_source: str) -> HostCoreSettings:
    return HostCoreSettings(
        deployment_commit="a" * 40,
        observation_mode=observation_mode,
        delivery_owner=owner,
        wechat_gate_source=gate_source,
        edge_token="token",
        verification_pepper="verification",
        invite_pepper="invite",
        standard_daily_email_limit=10,
        priority_daily_email_limit=100,
        standard_active_subscription_limit=5,
        priority_active_subscription_limit=20,
        notification_daily_send_limit=1000,
        weather_gate_enabled=True,
        weather_threshold_mm=25.0,
        weather_latitude=22.5431,
        weather_longitude=114.0579,
        redis_url=None,
    )


def local_result() -> dict[str, object]:
    return {
        "success": True,
        "wechatGate": {
            "allowed": False,
            "source": "airflow-host",
            "evaluatedAt": "2026-09-03T00:00:00+00:00",
            "validUntil": "2026-09-04T00:00:00+00:00",
            "revision": 1,
        },
    }


def test_dual_mode_persists_locally_but_uses_fresh_legacy_gate() -> None:
    legacy = {
        "success": True,
        "wechatGate": {
            "allowed": True,
            "evaluatedAt": "2026-09-03T00:00:00Z",
            "validUntil": "2026-09-03T00:10:00Z",
            "revision": 2,
        },
    }
    with (
        patch.object(
            api,
            "_settings",
            return_value=settings(
                observation_mode="dual", owner="cloudflare", gate_source="legacy"
            ),
        ),
        patch.object(api, "ingest_observation", return_value=local_result()) as local,
        patch.object(api, "_forward_legacy_observation", return_value=legacy) as forward,
    ):
        result = api.internal_observation({"venue_id": "tops"})
    local.assert_called_once()
    forward.assert_called_once()
    assert result["legacyForwarded"] is True
    assert result["wechatGate"] == legacy["wechatGate"]


def test_host_mode_never_calls_cloudflare_and_returns_host_gate() -> None:
    with (
        patch.object(
            api,
            "_settings",
            return_value=settings(
                observation_mode="host", owner="airflow_host", gate_source="host"
            ),
        ),
        patch.object(api, "ingest_observation", return_value=local_result()),
        patch.object(api, "_forward_legacy_observation") as forward,
    ):
        result = api.internal_observation({"venue_id": "tops"})
    forward.assert_not_called()
    assert result["legacyForwarded"] is False
    gate = result["wechatGate"]
    assert isinstance(gate, dict)
    assert gate["source"] == "airflow-host"


def test_pre_migration_legacy_failure_fails_open_for_wechat_only() -> None:
    with (
        patch.object(
            api,
            "_settings",
            return_value=settings(
                observation_mode="dual", owner="cloudflare", gate_source="legacy"
            ),
        ),
        patch.object(api, "ingest_observation", return_value=local_result()),
        patch.object(api, "_forward_legacy_observation", return_value=None),
        patch.object(api, "_migration_ready", return_value=False),
    ):
        result = api.internal_observation({"venue_id": "tops"})
    gate = result["wechatGate"]
    assert isinstance(gate, dict)
    assert gate["allowed"] is True
    assert gate["source"] == "migration-fail-open"
