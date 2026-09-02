from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_airflow_only_forwards_new_or_changed_observations() -> None:
    cache = source("src/wechat_airflow/notifications/observation_cache.py")

    assert 'OBSERVATION_FAILURE_RETRY_SECONDS_ENV = "WEBAPP_OBSERVATION_FAILURE_RETRY_SECONDS"' in cache
    assert "OBSERVATION_HEARTBEAT" not in cache
    assert 'ObservationAction = Literal["forward", "skip_success", "skip_retry"]' in cache
    assert 'if entry["last_success_at"] > 0:' in cache
    assert 'action: ObservationAction = "skip_success"' in cache
    assert "_STATE_VERSION = 3" in cache
    assert '"venues"' not in cache


def test_worker_has_no_observation_or_gate_heartbeat() -> None:
    dedupe = source("webapp/cloudflare/observation-dedupe.ts")
    policy = source("webapp/cloudflare/free-tier-observation.ts")
    entry = source("webapp/cloudflare/subscription-gated-entry.ts")

    assert 'const OBSERVATION_KEY_VERSION = "v3"' in dedupe
    assert "OBSERVATION_HEARTBEAT" not in dedupe
    assert 'FreeTierObservationAction = "forward" | "skip"' in policy
    assert '"heartbeat"' not in policy
    assert "venue_observation_lightweight_heartbeat" not in entry
    scheduled = entry.split("async scheduled", 1)[1]
    assert "refreshWechatVenueGates" not in scheduled
    assert "invalidateObservationMatchingSafely" not in entry


def test_dashboard_network_refresh_is_user_driven() -> None:
    ui = source("webapp/src/Prototype.tsx")
    api = source("webapp/src/api.ts")

    assert "window.setInterval(() => void refresh(), 30_000)" not in ui
    assert "点击刷新读取最新记录" in ui
    assert "仅在手动刷新时读取" in ui
    assert 'onClick={() => void refresh(true)}' in ui
    assert 'url.pathname === "/api/bootstrap"' not in api
    assert 'path = options.force ? "/api/bootstrap?refresh=1" : "/api/bootstrap"' in api
    assert "DASHBOARD_CLIENT_CACHE_MS = 86_400_000" in api


def test_current_snapshot_preserves_new_subscription_matching() -> None:
    worker = source("webapp/cloudflare/index.ts")
    snapshot = source("webapp/cloudflare/current-observation.ts")
    migration = source("webapp/migrations/0017_add_current_observation_snapshots.sql")

    assert "currentObservationSnapshotStatement" in worker
    assert "enqueueCurrentSnapshotMatches" in worker
    assert "matchedCurrentAvailability" in worker
    assert "current_observation_snapshots" in snapshot
    assert "slotMatchesWeekday" in snapshot
    assert "slotMatchesTimeRange" in snapshot
    assert "current_observation_snapshots" in migration
    assert "PRIMARY KEY" in migration


def test_dashboard_health_is_explicitly_last_known_state() -> None:
    worker = source("webapp/cloudflare/index.ts")
    ui = source("webapp/src/Prototype.tsx")

    assert "INSPECTION_FRESHNESS_MS" not in worker
    assert "场地最近状态" in ui
    assert "最近记录正常" in ui
    assert "记录生成于" in ui
