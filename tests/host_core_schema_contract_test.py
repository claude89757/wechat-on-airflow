from __future__ import annotations

from pathlib import Path

from wechat_airflow.host_core.schema import SCHEMA_STATEMENTS, SCHEMA_VERSION


def test_host_core_schema_is_isolated_from_airflow_metadata_tables() -> None:
    schema = "\n".join(SCHEMA_STATEMENTS)
    assert SCHEMA_VERSION.startswith("0.7.0-host-core")
    assert "CREATE SCHEMA IF NOT EXISTS zacks" in schema
    assert "CREATE TABLE IF NOT EXISTS zacks.subscriptions" in schema
    assert "CREATE TABLE IF NOT EXISTS zacks.subscription_venues" in schema
    assert "CREATE TABLE IF NOT EXISTS zacks.notification_outbox" in schema
    assert "CREATE TABLE IF NOT EXISTS zacks.system_email_outbox" in schema
    assert "CREATE TABLE IF NOT EXISTS zacks.wechat_delivery_incidents" in schema
    assert "UNIQUE (subscription_id, event_key)" in schema
    assert "ON zacks.subscription_venues(venue_id, subscription_id)" in schema
    assert "CREATE TABLE IF NOT EXISTS airflow." not in schema


def test_edge_runtime_has_no_delivery_cron_after_cutover() -> None:
    root = Path(__file__).parents[1]
    edge = (root / "webapp" / "cloudflare" / "edge-entry.ts").read_text(encoding="utf-8")
    worker = (root / "src" / "wechat_airflow" / "host_core" / "worker.py").read_text(
        encoding="utf-8"
    )
    assert "cloudflare_edge_cron_ignored_after_host_cutover" in edge
    assert "send_template_email" in worker
    assert "zacks.notification_outbox" in worker


def test_host_database_is_the_source_of_truth_and_redis_is_optional() -> None:
    root = Path(__file__).parents[1]
    settings = (root / "src" / "wechat_airflow" / "host_core" / "settings.py").read_text(
        encoding="utf-8"
    )
    service = (root / "src" / "wechat_airflow" / "host_core" / "service.py").read_text(
        encoding="utf-8"
    )
    assert "redis_url: str | None" in settings
    assert "zacks.subscription_events" in service
    assert "zacks.notification_outbox" in service
    assert "redis" not in service.lower()
