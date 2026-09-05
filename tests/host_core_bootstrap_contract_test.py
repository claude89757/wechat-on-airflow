from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text()


def test_prepare_only_enables_delivery_after_migration_and_routing():
    script = read("scripts/host_core_release.sh")
    assert script.index("remote prepare-runtime |") < script.index("remote sync-secrets")
    assert script.index("remote sync-secrets") < script.index("    export_snapshot")
    assert script.index("    export_snapshot") < script.index("    remote prepare-routing")
    assert script.index("    deploy_edge production") < script.index("    remote cutover")
    assert "remote rollback" not in script
    assert "set -Eeuo pipefail" in script and "trap recover EXIT" in script
    assert "trap 'exit 143' TERM" in script


def test_bootstrap_does_not_require_redis_or_worker_readiness():
    compose = yaml.safe_load(read("docker-compose.yml"))
    for name in (
        "zacks-api",
        "zacks-notification-worker",
        "zacks-wechat-worker",
        "zacks-secret-sync",
    ):
        assert set(compose["services"][name]["depends_on"]) == {"postgresql"}
    script = read("scripts/host_core_production.py")
    prepare = script.split("def prepare_runtime(", 1)[1].split("def sync_secrets", 1)[0]
    assert '"--no-deps"' in prepare
    assert "_wait_for_local_health" in prepare
    assert "set_delivery_enabled(False" in prepare


def test_failure_recovery_does_not_require_api_and_never_reactivates_d1():
    source = read("scripts/host_core_production.py")
    pause = source.split("def pause_host_delivery", 1)[1].split("def activate_workers", 1)[0]
    assert "one_shot(" in pause
    assert "local_health(" not in pause
    assert 'compose("stop", "zacks-notification-worker", "zacks-wechat-worker")' in pause
    assert "def rollback(" not in source


def test_edge_token_is_not_a_command_argument():
    script = read("scripts/host_core_production.py")
    sync = script.split("def sync_secrets", 1)[1].split("def migrate_sql", 1)[0]
    assert "input_text=edge_token" in sync
    assert "set -eu" in sync and "pipefail" not in sync
    assert "stdin=subprocess.DEVNULL" in script or "subprocess.DEVNULL" in script
