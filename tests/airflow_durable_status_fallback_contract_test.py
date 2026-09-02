from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_production_worker_uses_durable_status_fallback() -> None:
    wrangler = json.loads(
        (ROOT / "webapp/wrangler.jsonc").read_text(encoding="utf-8")
    )
    assert wrangler["main"] == "./cloudflare/resilient-entry.ts"
    assert wrangler["durable_objects"]["bindings"] == [
        {
            "name": "VENUE_STATUS_STORE",
            "class_name": "VenueStatusObject",
        }
    ]
    assert wrangler["migrations"] == [
        {
            "tag": "venue-status-v1",
            "new_sqlite_classes": ["VenueStatusObject"],
        }
    ]


def test_observation_snapshot_is_recorded_before_d1_processing() -> None:
    entry = (ROOT / "webapp/cloudflare/resilient-entry.ts").read_text(
        encoding="utf-8"
    )
    capture = entry.index("await captureObservationSnapshot(request, env)")
    d1_processing = entry.index("response = await worker.fetch(request, env as never, context)")
    assert capture < d1_processing
    assert 'url.pathname === "/api/venue-status-snapshot"' in entry
    assert 'X-Zacks-Dashboard-Source", "airflow-durable-status"' in entry


def test_airflow_reseeds_once_without_restoring_heartbeats() -> None:
    cache = (ROOT / "src/wechat_airflow/notifications/observation_cache.py").read_text(
        encoding="utf-8"
    )
    assert "webapp-observation-state-v4.json" in cache
    assert "OBSERVATION_HEARTBEAT" not in cache
    assert 'action = "skip_success"' in cache
    assert "Stable empty observations never cross the network again" in cache
