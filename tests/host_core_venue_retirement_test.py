from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from wechat_airflow.host_core import database, service, wechat_worker
from wechat_airflow.host_core.domain import (
    DURABLE_VENUES,
    RETIRED_VENUES,
    VENUES,
    active_venue_status,
    validate_observation,
    validate_subscription,
)
from wechat_airflow.host_core.health import venue_observation_health

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 1, 4, tzinfo=UTC)


def policy():
    return (
        yaml.safe_load((ROOT / "config/active-components.yaml").read_text()),
        yaml.safe_load((ROOT / "config/host-core-contract.yaml").read_text()),
    )


def rows():
    return [
        {"venue_id": venue_id, "healthy": True, "last_inspection_at": NOW} for venue_id in VENUES
    ]


def report(venues):
    manifest, contract = policy()
    return venue_observation_health(
        venues, manifest=manifest, contract=contract, now=NOW, since=NOW - timedelta(minutes=1)
    )


def test_date_pause_upgrade_keeps_retired_venue_seed_identity():
    # 0.10.0 intentionally adds date preferences and delivery-qualification DDL.
    # The approved routine upgrade retains the original 27-row venue seed;
    # withdrawing a producer must never delete its durable business identity.
    assert database.SCHEMA_REVISION == (
        "0.7.0-host-core-v1:3cf7737f5763852d193fe8ae43ff429c8fb01e9327f911207fc4baa1ebef7ed6"
    )
    assert len(VENUES) == 26
    assert RETIRED_VENUES == {"baoti": "宝安网球中心"}
    assert len(DURABLE_VENUES) == 27
    assert DURABLE_VENUES["baoti"] == "宝安网球中心"


def test_retired_venue_is_preserved_but_excluded_from_active_catalog_and_health():
    retired = {
        "venue_id": "baoti",
        "healthy": False,
        "last_inspection_at": NOW - timedelta(days=1),
    }
    stored = [*rows(), retired]
    before = deepcopy(stored)
    result = report(stored)
    assert result["ok"] is True
    assert result["storedVenueCount"] == 27
    assert result["checkedVenueCount"] == 26
    assert result["retiredVenueCount"] == 1
    assert result["retiredVenues"][0]["last_inspection_at"] == retired["last_inspection_at"]
    assert result["retiredVenues"][0]["retirement"]["approved_on"] == "2026-11-01"
    assert active_venue_status(stored) == rows()
    assert stored == before


@pytest.mark.parametrize("missing", [False, True])
def test_unknown_extra_venue_cannot_replace_a_missing_active_venue_or_be_silently_hidden(missing):
    stored = rows()[int(missing) :] + [
        {"venue_id": "unknown", "healthy": True, "last_inspection_at": NOW}
    ]
    result = report(stored)
    assert result["ok"] is False
    assert result["catalogMatches"] is False
    assert result["unknownVenueIds"] == ["unknown"]
    with pytest.raises(ValueError, match="catalog"):
        active_venue_status(stored)


@pytest.mark.parametrize("missing", [False, True])
def test_missing_or_duplicate_active_rows_fail_catalog_acceptance(missing):
    stored = rows()[1:] if missing else [*rows(), rows()[0]]
    assert report(stored)["ok"] is False
    with pytest.raises(ValueError, match="catalog"):
        active_venue_status(stored)


@pytest.mark.parametrize("unhealthy,stale", [(True, False), (False, True)])
def test_retirement_does_not_relax_active_venue_health_or_freshness(unhealthy, stale):
    stored = rows()
    stored[0]["healthy"] = not unhealthy
    if stale:
        stored[0]["last_inspection_at"] = NOW - timedelta(minutes=11)
    assert report(stored)["ok"] is False


@pytest.mark.parametrize("change", ["extra_retirement", "reactivation", "approval_date"])
def test_only_the_exact_approved_venue_retirement_is_allowed(change):
    manifest, contract = policy()
    if change == "extra_retirement":
        contract["retired_venues"]["tops"] = dict(contract["retired_venues"]["baoti"])
    elif change == "reactivation":
        manifest["active_dags"].append({"dag_id": "宝安网球中心巡检"})
    else:
        contract["retired_venues"]["baoti"]["approved_on"] = "2026-10-31"
    with pytest.raises(ValueError, match="approved venue policy"):
        venue_observation_health(rows(), manifest=manifest, contract=contract, now=NOW, since=NOW)


def test_retired_venue_rejects_new_subscriptions_and_observations():
    with pytest.raises(ValueError, match="场地"):
        validate_subscription(
            {"venueIds": ["baoti"], "startTime": "18:00", "endTime": "20:00"},
            priority=False,
        )
    with pytest.raises(ValueError):
        validate_observation({"venue_id": "baoti", "healthy": True, "slots": []})


def test_retired_wechat_intent_is_cancelled_before_any_database_or_sender_call(monkeypatch):
    forbidden = Mock(side_effect=AssertionError("retired venue must not request delivery"))
    finished = Mock()
    monkeypatch.setattr(service, "transaction", forbidden)
    monkeypatch.setattr(wechat_worker, "transaction", forbidden)
    monkeypatch.setattr(wechat_worker, "_finish", finished)
    row = {"id": "historical-intent", "venue_id": "baoti"}
    assert wechat_worker._prepare(row, "test-worker") is False
    finished.assert_called_once_with(row, "test-worker", "cancelled", "no_active_subscription")
    forbidden.assert_not_called()
