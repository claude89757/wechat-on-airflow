from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_webapp_release_has_no_quota_fallback_or_legacy_branch() -> None:
    workflow = (ROOT / ".github/workflows/production-webapp.yml").read_text()
    assert "wrangler d1" not in workflow
    assert "deferred_quota" not in workflow
    assert "webapp_production_health.py" in workflow
    assert "config.d1_databases?.length" in workflow
    assert "config.triggers?.crons?.length" in workflow


def test_stateless_edge_release_requires_an_active_host_origin() -> None:
    workflow = (ROOT / ".github/workflows/production-webapp.yml").read_text()
    assert "require_existing_host_cutover" in workflow
    assert "The initial stateless-edge cutover must use Production Host Core" in workflow
    assert ".wrangler-stateless-edge-runtime.json" in workflow
    assert "Persistence: PostgreSQL on the Airflow host" in workflow


def test_archived_migration_reference_has_idempotent_schema() -> None:
    entry = (ROOT / "webapp/cloudflare/subscription-gated-entry.ts").read_text(encoding="utf-8")
    schema = (ROOT / "webapp/cloudflare/free-tier-schema.ts").read_text(encoding="utf-8")

    fetch_block = entry.split("async fetch", 1)[1].split("async scheduled", 1)[0]
    scheduled_block = entry.split("async scheduled", 1)[1]
    assert "ensureSchemaSafely" not in fetch_block
    assert "ensureSchemaSafely" in scheduled_block
    assert "free_tier_schema_applied" in entry
    assert "CREATE INDEX IF NOT EXISTS" in schema
    assert "PRAGMA optimize" in schema
    assert "system:free-tier-schema" in schema


def test_delivery_diagnostics_do_not_use_an_unbounded_outbox_aggregate() -> None:
    script = (ROOT / "scripts/diagnose_email_delivery_metrics.sh").read_text(encoding="utf-8")

    first_query = script.split("__EMAIL_DELIVERY_METRICS__", 1)[1].split(
        "__ADMIN_IDENTITY_DELIVERY_METRICS__", 1
    )[0]
    admin_query = script.split("__ADMIN_IDENTITY_DELIVERY_METRICS__", 1)[1].split(
        "__PROVIDER_STATUS_BREAKDOWN__", 1
    )[0]
    assert "WHERE provider_submitted_at >= day.start_utc" in first_query
    assert "WHERE n.provider_submitted_at >= day.start_utc" in admin_query
    assert "AS has_retention_expired" in script
    assert "AS retention_expired" not in script
