from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runtime_secrets_are_ready_before_host_processes_start() -> None:
    workflow = read(".github/workflows/production-host-core.yml")
    script = read("scripts/host_core_production.py")
    secret_sync = read("src/wechat_airflow/host_core/secret_sync.py")

    assert workflow.index("rollback_required=true") < workflow.index("deploy_edge false false true")
    assert workflow.index("remote sync-secrets") < workflow.index("remote deploy-shadow")
    assert 'variable_get("WEBAPP_OBSERVATION_API_TOKEN")' in script
    assert "input_text=edge_token" in script
    assert 'compose("--profile", "maintenance", "build", "zacks-secret-sync"' in script
    assert 'EDGE_TOKEN_FILENAME = "zacks_edge_token"' in secret_sync
    assert "install_edge_token(arguments.secret_dir, token)" in secret_sync
    assert "def _staged_edge_token" in secret_sync


def test_shadow_start_waits_for_health_before_tunnel_activation() -> None:
    script = read("scripts/host_core_production.py")
    deploy = script.split("def deploy_shadow(target_commit):", 1)[1].split(
        "def sync_secrets", 1
    )[0]

    assert "def _wait_for_local_health" in script
    assert "time.monotonic()" in script
    assert deploy.index("_wait_for_local_health(target_commit)") < deploy.index(
        '"--apply"'
    )


def test_pre_activation_rollback_does_not_require_the_failed_local_api() -> None:
    script = read("scripts/host_core_production.py")
    rollback = script.split("def rollback(target_commit):", 1)[1].split(
        "def health(", 1
    )[0]

    assert 'variable_get("ZACKS_DELIVERY_OWNER")' in rollback
    assert "local_health(" not in rollback
    assert 'compose("stop", "zacks-notification-worker", "zacks-api")' in rollback


def test_edge_token_is_never_put_in_a_command_argument() -> None:
    script = read("scripts/host_core_production.py")
    sync = script.split("def sync_secrets(target_commit):", 1)[1].split(
        "def migrate(", 1
    )[0]

    assert "input_text=edge_token" in sync
    assert '"AIRFLOW_PUSH_TOKEN"' not in sync
    assert "edge_token +" not in sync.split("input_text=edge_token", 1)[0]
