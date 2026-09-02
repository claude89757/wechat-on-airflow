from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_airflow_empty_observations_have_no_time_based_heartbeat() -> None:
    cache = (
        ROOT / "src/wechat_airflow/notifications/observation_cache.py"
    ).read_text(encoding="utf-8")

    assert "OBSERVATION_HEARTBEAT" not in cache
    assert "VenueHeartbeat" not in cache
    assert 'action = "skip_success"' in cache
    assert "Stable empty observations never cross the network again" in cache
    assert "Available slots continue with a cheap indexed rematch probe" in cache


def test_worker_identical_observations_never_write_a_heartbeat() -> None:
    dedupe = (ROOT / "webapp/cloudflare/observation-dedupe.ts").read_text(
        encoding="utf-8"
    )
    policy = (ROOT / "webapp/cloudflare/free-tier-observation.ts").read_text(
        encoding="utf-8"
    )
    entry = (ROOT / "webapp/cloudflare/subscription-gated-entry.ts").read_text(
        encoding="utf-8"
    )

    assert "OBSERVATION_HEARTBEAT" not in dedupe
    assert 'FreeTierObservationAction = "forward" | "skip"' in policy
    assert "UPDATE observation_ingest_state" not in policy
    assert "INSERT INTO venue_status" not in policy
    assert 'heartbeat:' not in entry
    assert "venue_observation_lightweight_heartbeat" not in entry


def test_dashboard_refresh_is_user_driven_and_health_is_last_known() -> None:
    prototype = (ROOT / "webapp/src/Prototype.tsx").read_text(encoding="utf-8")
    api = (ROOT / "webapp/src/api.ts").read_text(encoding="utf-8")
    worker = (ROOT / "webapp/cloudflare/index.ts").read_text(encoding="utf-8")

    assert "window.setInterval(() => void refresh()" not in prototype
    assert 'onClick={() => void refresh(true)}' in prototype
    assert "页面数据由用户手动刷新" in prototype
    assert "点击顶部按钮获取最新数据" in prototype
    assert "后台巡检与页面刷新分开" in prototype
    assert 'const requestPath = options.force ? "/api/bootstrap?refresh=1"' in api
    assert "INSPECTION_FRESHNESS_MS" not in worker
    assert "healthy: Boolean(venue.healthy)" in worker
