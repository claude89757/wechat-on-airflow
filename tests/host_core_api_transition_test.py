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


def test_host_mode_persists_and_never_calls_remote_network():
    with (
        patch.object(
            api,
            "_settings",
            return_value=settings(
                observation_mode="host", owner="airflow_host", gate_source="host"
            ),
        ),
        patch.object(api, "ingest_observation", return_value=local_result()) as ingest,
        patch(
            "wechat_airflow.host_core.control.runtime_state",
            return_value={"delivery_enabled": True},
        ),
        patch.object(
            api.requests, "post", side_effect=AssertionError("Cloudflare forbidden")
        ) as remote,
    ):
        result = api.internal_observation({"venue_id": "tops"})
    ingest.assert_called_once_with({"venue_id": "tops"})
    remote.assert_not_called()
    assert result["wechatGate"]["source"] == "airflow-host"


def test_paused_owner_cannot_allow_legacy_cached_gate():
    value = local_result()
    value["wechatGate"]["allowed"] = True
    with (
        patch.object(
            api,
            "_settings",
            return_value=settings(observation_mode="host", owner="paused", gate_source="host"),
        ),
        patch.object(api, "ingest_observation", return_value=value),
        patch(
            "wechat_airflow.host_core.control.runtime_state",
            return_value={"delivery_enabled": False},
        ),
        patch.object(api.requests, "post", side_effect=AssertionError("legacy forbidden")),
    ):
        result = api.internal_observation({"venue_id": "tops"})
    assert result["wechatGate"]["allowed"] is False


def test_legacy_forwarding_is_not_in_the_runtime():
    assert not hasattr(api, "_forward_legacy_observation")
