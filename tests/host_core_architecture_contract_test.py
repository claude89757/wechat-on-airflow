from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_release_version_is_consistent() -> None:
    project = read("pyproject.toml")
    package = read("src/wechat_airflow/__init__.py")
    changelog = read("CHANGELOG.md")

    assert 'version = "0.7.0"' in project
    assert '__version__ = "0.7.0"' in package
    assert "## [0.7.0] - 2026-09-04" in changelog
    assert not (ROOT / "scripts" / "normalize_host_core_types.py").exists()


def test_cloudflare_is_stateless_after_cutover() -> None:
    import json

    wrangler = json.loads(read("webapp/wrangler.jsonc"))
    edge = read("webapp/cloudflare/edge-entry.ts")
    runtime = yaml.safe_load(read("config/runtime-target.yaml"))
    assert wrangler["main"] == "./cloudflare/edge-entry.ts"
    assert not wrangler.get("d1_databases")
    assert wrangler["triggers"]["crons"] == []
    assert "legacyRuntime: false" in edge
    assert "import " not in edge
    assert "legacyWorker" not in edge and "env.DB" not in edge
    assert runtime["managed_services"]["webapp"]["d1"]["mode"] == "unbound_migration_archive"
    assert runtime["managed_services"]["webapp"]["d1"]["deletion_in_cutover"] is False


def test_postgresql_host_core_is_the_durable_business_owner() -> None:
    runtime = yaml.safe_load(read("config/runtime-target.yaml"))
    contract = yaml.safe_load(read("config/host-core-contract.yaml"))
    compose = yaml.safe_load(read("docker-compose.yml"))

    assert runtime["target"]["database"]["business_schema"] == "zacks"
    assert runtime["target"]["database"]["business_store_owner"] == "airflow_host"
    assert runtime["target"]["broker"]["durable_business_role"] == "none"
    assert contract["ownership"]["durable_business_state"] == "postgresql:zacks"
    assert contract["ownership"]["redis"] == "optional_acceleration_only"
    assert {"zacks-api", "zacks-notification-worker", "zacks-secret-sync"}.issubset(
        compose["services"]
    )


def test_host_core_provider_secrets_are_not_airflow_runtime_secrets() -> None:
    runtime = yaml.safe_load(read("config/runtime-target.yaml"))["target"]

    assert set(runtime["runtime_secrets"]) == {
        "AIRFLOW_FERNET_KEY",
        "AIRFLOW_API_SECRET_KEY",
        "AIRFLOW_JWT_SECRET",
        "AIRFLOW_DATABASE_PASSWORD",
        "AIRFLOW_PASSWORD",
    }
    assert runtime["host_core_secret_files"] == {
        "TENCENT_SECRET_ID": "tencent_secret_id",
        "TENCENT_SECRET_KEY": "tencent_secret_key",
        "TENCENT_REGION": "tencent_region",
        "EMAIL_FROM_ADDRESS": "email_from_address",
        "EMAIL_REPLY_TO": "email_reply_to",
        "EMAIL_TEMPLATE_ID": "email_template_id",
    }


def test_repository_invariants_no_longer_assign_delivery_to_d1() -> None:
    agents = read("AGENTS.md")
    architecture = read("ARCHITECTURE.md")
    active = read("config/active-components.yaml")

    assert "PostgreSQL schema `zacks` is the only durable business store" in agents
    assert "Cloudflare has no durable business ownership" in architecture
    assert "airflow_host_is_the_only_email_delivery_owner_after_cutover" in active
    assert "webapp_is_the_only_email_delivery_owner" not in active


def test_cutover_uses_quota_independent_sql_export_and_one_delivery_owner() -> None:
    workflow = read(".github/workflows/production-host-core.yml")
    release = read("scripts/host_core_release.sh")
    assert "scripts/github_release_gate.py" in workflow
    assert "scripts/host_core_release.sh" in workflow
    assert "npx wrangler d1 export zacks-tennis-alerts" in release
    assert "remote migrate-sql" in release
    assert "remote pause-host-delivery" in release
    assert "remote rollback" not in release
    assert "-n -o BatchMode=yes" in release
    assert "ServerAliveInterval=15" in release
    assert "set -Eeuo pipefail" in release
    assert "migration" in read("docs/runbooks/host-core-cutover.md").lower()
