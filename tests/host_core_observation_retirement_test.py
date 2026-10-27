from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from wechat_airflow.host_core.health import RETIRED_OBSERVATION_SCOPE, observation_scope_health

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 27, 4, tzinfo=UTC)


def policy():
    return (
        yaml.safe_load((ROOT / "config/active-components.yaml").read_text()),
        yaml.safe_load((ROOT / "config/host-core-contract.yaml").read_text()),
    )


def active_scopes():
    return [
        {"observation_key": f"active-{index}:task", "healthy": True, "last_seen_at": NOW}
        for index in range(30)
    ]


def report(scopes):
    manifest, contract = policy()
    return observation_scope_health(scopes, manifest=manifest, contract=contract, now=NOW)


def test_exact_retired_scope_is_visible_but_not_required_to_keep_polling():
    retired = {
        "observation_key": RETIRED_OBSERVATION_SCOPE,
        "healthy": False,
        "last_seen_at": NOW - timedelta(days=7),
    }
    scopes = [*active_scopes(), retired]
    original = deepcopy(scopes)

    result = report(scopes)

    assert result["ok"] is True
    assert result["storedScopeCount"] == 31
    assert result["checkedScopeCount"] == 30
    assert result["retiredScopeCount"] == 1
    assert result["retiredScopes"] == [
        {
            **retired,
            "retirement": policy()[1]["retired_observation_scopes"][RETIRED_OBSERVATION_SCOPE],
        }
    ]
    assert scopes == original


@pytest.mark.parametrize(
    "observation_key",
    ["szw:check_and_notify_day_0", "gba:check_and_notify_day_3", "unknown:task"],
)
@pytest.mark.parametrize(
    "healthy,last_seen_at", [(False, NOW), (True, NOW - timedelta(minutes=11))]
)
def test_active_and_unlisted_bad_scopes_still_fail(observation_key, healthy, last_seen_at):
    scopes = [
        *active_scopes(),
        {"observation_key": observation_key, "healthy": healthy, "last_seen_at": last_seen_at},
    ]
    result = report(scopes)
    assert result["ok"] is False
    assert result["checkedScopeCount"] == 31
    assert result["retiredScopeCount"] == 0


def test_retired_history_does_not_substitute_for_active_observation_evidence():
    assert report([])["ok"] is False
    assert (
        report(
            [{"observation_key": RETIRED_OBSERVATION_SCOPE, "healthy": True, "last_seen_at": NOW}]
        )["ok"]
        is False
    )


def test_reactivating_retired_task_fails_closed():
    manifest, contract = policy()
    component = next(
        entry for entry in manifest["active_dags"] if entry["dag_id"] == "深圳湾网球场巡检"
    )
    component["tasks"].append("check_and_notify_day_3")
    with pytest.raises(ValueError, match="approved task policy"):
        observation_scope_health(active_scopes(), manifest=manifest, contract=contract, now=NOW)


def test_retirement_policy_cannot_ignore_another_unhealthy_scope():
    manifest, contract = policy()
    contract["retired_observation_scopes"]["unknown:task"] = dict(
        contract["retired_observation_scopes"][RETIRED_OBSERVATION_SCOPE]
    )
    with pytest.raises(ValueError, match="approved task policy"):
        observation_scope_health(active_scopes(), manifest=manifest, contract=contract, now=NOW)
