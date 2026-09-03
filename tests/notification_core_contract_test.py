from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_notification_core_services_share_the_airflow_host_data_plane() -> None:
    compose = yaml.safe_load(read("docker-compose.yml"))
    services = compose["services"]
    assert "zacks-notification-api" in services
    assert "zacks-notification-worker" in services
    assert services["zacks-notification-api"]["command"] == (
        "python -m wechat_airflow.notification_core.api"
    )
    assert services["zacks-notification-worker"]["command"] == (
        "python -m wechat_airflow.notification_core.worker"
    )
    assert services["zacks-notification-api"]["environment"]["ZACKS_CORE_REDIS_URL"].endswith(
        "/1"
    )


def test_postgresql_is_authoritative_and_redis_is_optional() -> None:
    schema = read("src/wechat_airflow/notification_core/schema.sql")
    repository = read("src/wechat_airflow/notification_core/repository.py")
    api = read("src/wechat_airflow/notification_core/api.py")
    assert "CREATE SCHEMA IF NOT EXISTS zacks_core" in schema
    assert "UNIQUE" in schema
    assert "FOR UPDATE SKIP LOCKED" in repository
    assert "Redis is deliberately optional" in api
    assert "status = 'uncertain'" in repository
    assert "not replayed automatically" in repository


def test_cloudflare_is_a_bounded_subscription_source_not_the_delivery_path() -> None:
    wrapper = read("webapp/cloudflare/subscription-gated-entry.ts")
    admin = read("scripts/notification_core_admin.py")
    assert "/api/internal/subscription-snapshot" in wrapper
    assert "LIMIT 100000" in wrapper
    assert "http://zacks-notification-api:8091/api/internal/observations" in admin
    assert 'Variable.set(name, value)' in admin


def test_wechat_fails_open_only_for_unknown_gate_state() -> None:
    publisher = read("src/wechat_airflow/notifications/webapp.py")
    assert "gate_unknown_fail_open" in publisher
    assert "allowed = explicit_allowed is not False" in publisher
    assert "fresh_deny" in publisher


def test_version_is_070() -> None:
    assert read("VERSION").strip() == "0.7.0"
    assert 'version="0.7.0"' in read("src/wechat_airflow/notification_core/api.py")
