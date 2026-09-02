from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_webapp_release_tolerates_only_the_known_d1_quota_error() -> None:
    workflow = (ROOT / ".github/workflows/production-webapp.yml").read_text(encoding="utf-8")

    assert "d1_quota_exhausted" in workflow
    assert "exceeded D1's free tier daily row read limit" in workflow
    assert "\\[code: 7500\\]" in workflow
    assert "Unexpected D1 failure" in workflow
    assert "return 75" in workflow
    assert "webapp_deployment_identity.py" in workflow
    assert "webapp_production_health.py" in workflow

    apply_block = workflow.split("deploy_apply)", 1)[1].split("*)", 1)[0]
    assert apply_block.index("npx wrangler d1 migrations apply") < apply_block.rindex(
        "npx wrangler deploy"
    )


def test_deployed_worker_has_an_idempotent_quota_reset_self_heal() -> None:
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
