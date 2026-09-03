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


def test_cloudflare_is_stateless_after_cutover() -> None:
    wrangler = read("webapp/wrangler.jsonc")
    edge = read("webapp/cloudflare/edge-entry.ts")
    runtime = yaml.safe_load(read("config/runtime-target.yaml"))
    webapp = runtime["managed_services"]["webapp"]

    assert '"main": "./cloudflare/edge-entry.ts"' in wrangler
    assert '"HOST_CORE_CUTOVER": "true"' in wrangler
    assert 'source: "airflow-host"' in edge
    assert "cloudflare_edge_cron_ignored_after_host_cutover" in edge
    assert 'from "./index"' not in edge
    assert 'from "./deployment-entry"' not in edge
    assert webapp["runtime"] == "cloudflare_worker_stateless_edge"
    assert webapp["business_state"] == "none_after_cutover"
    assert webapp["scheduled_notification_work"] == "disabled_after_cutover"
    assert webapp["d1"]["mode"] == "read_only_rollback_window"
    assert webapp["d1"]["deletion_in_cutover"] is False


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


def test_repository_invariants_no_longer_assign_delivery_to_d1() -> None:
    agents = read("AGENTS.md")
    architecture = read("ARCHITECTURE.md")
    active = read("config/active-components.yaml")

    assert "PostgreSQL schema `zacks` is the only durable business store" in agents
    assert "Cloudflare has no durable business ownership" in architecture
    assert "airflow_host_is_the_only_email_delivery_owner_after_cutover" in active
    assert "webapp_is_the_only_email_delivery_owner" not in active


def test_cutover_keeps_one_email_owner_and_preserves_d1() -> None:
    workflow = read(".github/workflows/production-host-core.yml")
    runbook = read("docs/runbooks/host-core-cutover.md")

    assert "remote enable-dual" in workflow
    assert "remote migrate --pass-name final" in workflow
    assert "remote cutover" in workflow
    assert "deploy_edge true false false" in workflow
    assert "remote rollback" in workflow
    assert "Real test notifications: none" in workflow
    assert "D1" in runbook
    assert "delete" not in workflow.lower()
