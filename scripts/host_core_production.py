#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
LOCAL_HEALTH = "http://127.0.0.1:8090/zacks-api/api/healthz"
LOCAL_READY = "http://127.0.0.1:8090/zacks-api/api/readyz"
PUBLIC_HEALTH = "https://zacks.claude89757.cc/api/healthz"
LOCAL_OBSERVATION_URL = "http://zacks-api:8090/zacks-api/api/internal/observations"
LEGACY_OBSERVATION_URL = "https://zacks.claude89757.cc/api/internal/observations"


def run(
    command: list[str],
    *,
    check: bool = True,
    capture: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
    )


def compose(*arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return run([*COMPOSE, *arguments], env=env)


def compose_exec(service: str, *arguments: str, capture: bool = False) -> str:
    completed = run(
        [*COMPOSE, "exec", "-T", service, *arguments],
        capture=capture,
    )
    return completed.stdout.strip() if capture and completed.stdout else ""


def running_services() -> set[str]:
    return set(
        run(
            [*COMPOSE, "ps", "--status", "running", "--services"],
            capture=True,
        ).stdout.splitlines()
    )


def assert_target(target_commit: str) -> None:
    if len(target_commit) != 40 or any(
        character not in "0123456789abcdef" for character in target_commit.lower()
    ):
        raise RuntimeError("target commit must be a full SHA")
    head = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    if head != target_commit:
        raise RuntimeError(f"worktree commit mismatch: expected {target_commit}, got {head}")


def variable_set(name: str, value: str) -> None:
    compose_exec("airflow-api-server", "airflow", "variables", "set", name, value)


def host_python(script: str, *, capture: bool = False) -> str:
    return compose_exec("zacks-api", "python", "-c", script, capture=capture)


def check_ses_credentials() -> None:
    result = host_python(
        "from wechat_airflow.host_core.settings import load_tencent_email_settings; "
        "load_tencent_email_settings(); print('ready')",
        capture=True,
    )
    if result.strip() != "ready":
        raise RuntimeError("host Tencent SES credentials are unavailable")


def _curl_json(url: str) -> dict[str, Any]:
    completed = run(
        ["curl", "--fail", "--silent", "--show-error", url],
        capture=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"health endpoint returned invalid JSON: {url}")
    return value


def local_health(expected_commit: str | None = None) -> dict[str, Any]:
    value = _curl_json(LOCAL_HEALTH)
    if value.get("ok") is not True:
        raise RuntimeError("local host-core health check failed")
    if expected_commit and value.get("deploymentCommit") != expected_commit:
        raise RuntimeError("local host-core deployment identity mismatch")
    return value


def local_ready() -> dict[str, Any]:
    value = _curl_json(LOCAL_READY)
    if value.get("ok") is not True:
        raise RuntimeError("local host-core readiness check failed")
    return value


def public_health(expected_commit: str) -> dict[str, Any]:
    value = _curl_json(PUBLIC_HEALTH)
    if value.get("ok") is not True:
        raise RuntimeError("public host-core health check failed")
    if value.get("deploymentCommit") != expected_commit:
        raise RuntimeError("public host-core deployment identity mismatch")
    if value.get("runtime") != "airflow-host":
        raise RuntimeError("public API is not routed to the Airflow-host runtime")
    return value


def preflight(target_commit: str) -> dict[str, Any]:
    assert_target(target_commit)
    compose("config", "--quiet")
    disk = os.statvfs(ROOT)
    free_bytes = disk.f_bavail * disk.f_frsize
    if free_bytes < 8_000_000_000:
        raise RuntimeError("less than 8 GB is available on the reliable repository filesystem")
    run([sys.executable, str(ROOT / "scripts" / "configure_zacks_tunnel.py")])
    return {
        "targetCommit": target_commit,
        "compose": "valid",
        "freeBytes": free_bytes,
        "tunnelPlan": "valid",
    }


def deploy_shadow(target_commit: str) -> dict[str, Any]:
    result = preflight(target_commit)
    environment = os.environ.copy()
    environment["DEPLOYMENT_COMMIT"] = target_commit
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("ZACKS_OBSERVATION_MODE", "cloudflare")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "legacy")
    compose(
        "up",
        "-d",
        "--build",
        "zacks-api",
        "zacks-notification-worker",
        env=environment,
    )
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "configure_zacks_tunnel.py"),
            "--apply",
            "--restart",
        ]
    )
    result.update(
        {
            "localHealth": local_health(target_commit),
            "deliveryOwner": "cloudflare",
            "observation": "cloudflare",
        }
    )
    return result


def sync_secrets(target_commit: str) -> dict[str, Any]:
    assert_target(target_commit)
    environment = os.environ.copy()
    environment["DEPLOYMENT_COMMIT"] = target_commit
    completed = compose(
        "--profile",
        "maintenance",
        "run",
        "--rm",
        "zacks-secret-sync",
        env=environment,
    )
    check_ses_credentials()
    return {
        "targetCommit": target_commit,
        "secretSync": "complete",
        "returnCode": completed.returncode,
    }


def migrate(target_commit: str, *, pass_name: str) -> dict[str, Any]:
    assert_target(target_commit)
    script = (
        """
import json
from wechat_airflow.host_core.migration import fetch_snapshot, import_snapshot
from wechat_airflow.host_core.settings import load_settings
settings = load_settings()
snapshot = fetch_snapshot('https://zacks.claude89757.cc', settings.edge_token)
counts = import_snapshot(snapshot, source_revision=%r)
print(json.dumps({'success': True, 'counts': counts}, sort_keys=True))
"""
        % target_commit
    )
    output = host_python(script, capture=True)
    result = json.loads(output.splitlines()[-1])
    if result.get("success") is not True:
        raise RuntimeError("host-core migration did not report success")
    return {
        "targetCommit": target_commit,
        "pass": pass_name,
        "counts": result.get("counts", {}),
    }


def enable_dual(target_commit: str) -> dict[str, Any]:
    assert_target(target_commit)
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("ZACKS_OBSERVATION_MODE", "dual")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "legacy")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
    # One shared log volume holds the process-independent observation cache.
    # Removing only these state files forces one natural reseed per venue; it
    # does not alter any venue notification cache or Airflow metadata.
    compose_exec(
        "airflow-worker",
        "sh",
        "-ec",
        "rm -f /opt/airflow/logs/webapp-observation-state*.json "
        "/opt/airflow/logs/webapp-observation-state*.json.lock",
    )
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "cloudflare",
        "observation": "dual",
        "observationUrl": "local-compose",
    }


def shadow_evidence(target_commit: str) -> dict[str, Any]:
    assert_target(target_commit)
    script = """
import json
from sqlalchemy import text
from wechat_airflow.host_core.database import transaction
with transaction() as connection:
    row = connection.execute(text('''
        SELECT
          count(*) FILTER (WHERE last_inspection_at >= now() - interval '15 minutes') AS recent_venues,
          count(*) AS total_venues
        FROM zacks.venue_status
    ''')).mappings().one()
    subscriptions = connection.execute(text('''
        SELECT count(*) FROM zacks.subscriptions
        WHERE active = true AND active_until > now()
    ''')).scalar_one()
    outbox = connection.execute(text('SELECT count(*) FROM zacks.notification_outbox')).scalar_one()
print(json.dumps({
    'recentVenues': int(row['recent_venues'] or 0),
    'totalVenues': int(row['total_venues'] or 0),
    'activeSubscriptions': int(subscriptions or 0),
    'outboxRows': int(outbox or 0),
}, sort_keys=True))
"""
    evidence = json.loads(host_python(script, capture=True).splitlines()[-1])
    if int(evidence.get("totalVenues") or 0) != 26:
        raise RuntimeError("host-core venue catalog is incomplete")
    if int(evidence.get("recentVenues") or 0) < 20:
        raise RuntimeError("fewer than 20 venues naturally reseeded the host-core runtime")
    if int(evidence.get("activeSubscriptions") or 0) <= 0:
        raise RuntimeError("host-core migration contains no active subscriptions")
    return {"targetCommit": target_commit, **evidence}


def prepare_cutover(target_commit: str) -> dict[str, Any]:
    """Move reads and observations to the host while keeping all delivery paused."""
    assert_target(target_commit)
    check_ses_credentials()
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
    variable_set("ZACKS_OBSERVATION_MODE", "host")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "host")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    compose("stop", "zacks-notification-worker")
    compose("restart", "zacks-api")
    health = local_health(target_commit)
    ready = local_ready()
    if health.get("deliveryOwner") != "cloudflare":
        raise RuntimeError("delivery must remain paused before public edge cutover")
    if health.get("observationMode") != "host":
        raise RuntimeError("host observation mode did not activate before edge cutover")
    if "zacks-notification-worker" in running_services():
        raise RuntimeError("notification worker is still running during delivery pause")
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "cloudflare",
        "observation": "host",
        "notificationWorker": "stopped",
        "localHealth": health,
        "localReady": ready,
    }


def cutover(target_commit: str) -> dict[str, Any]:
    """Activate host delivery only after the public edge has been verified."""
    assert_target(target_commit)
    check_ses_credentials()
    health_before = local_health(target_commit)
    local_ready()
    if health_before.get("deliveryOwner") == "airflow_host":
        if "zacks-notification-worker" not in running_services():
            compose("up", "-d", "zacks-notification-worker")
        return {
            "targetCommit": target_commit,
            "deliveryOwner": "airflow_host",
            "alreadyActive": True,
            "localHealth": local_health(target_commit),
            "localReady": local_ready(),
        }
    if health_before.get("deliveryOwner") != "cloudflare":
        raise RuntimeError("unexpected delivery owner before host activation")
    if health_before.get("observationMode") != "host":
        raise RuntimeError("host observation mode must be active before delivery")

    mark = """
from sqlalchemy import text
from wechat_airflow.host_core.database import transaction
from wechat_airflow.host_core.domain import utc_now
with transaction() as connection:
    connection.execute(text('''
        UPDATE zacks.migration_state
        SET cutover_at = :now, updated_at = :now
        WHERE source = 'cloudflare-d1'
    '''), {'now': utc_now()})
"""
    host_python(mark)
    variable_set("ZACKS_DELIVERY_OWNER", "airflow_host")
    compose("up", "-d", "zacks-notification-worker")
    health = local_health(target_commit)
    ready = local_ready()
    if health.get("deliveryOwner") != "airflow_host":
        raise RuntimeError("local delivery owner did not switch to airflow_host")
    if "zacks-notification-worker" not in running_services():
        raise RuntimeError("host notification worker did not start")
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "airflow_host",
        "localHealth": health,
        "localReady": ready,
    }


def pause_host_delivery(target_commit: str) -> dict[str, Any]:
    """Fail closed without reactivating a potentially stale D1 sender."""
    assert_target(target_commit)
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
    variable_set("ZACKS_OBSERVATION_MODE", "host")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "host")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    compose("stop", "zacks-notification-worker")
    health = local_health(target_commit)
    ready = local_ready()
    if health.get("deliveryOwner") != "cloudflare":
        raise RuntimeError("host delivery did not enter the safe paused state")
    if "zacks-notification-worker" in running_services():
        raise RuntimeError("notification worker remains active after safe pause")
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "cloudflare",
        "observation": "host",
        "notificationWorker": "stopped",
        "safePause": True,
        "localHealth": health,
        "localReady": ready,
    }


def rollback(target_commit: str) -> dict[str, Any]:
    """Restore the legacy path only before host delivery has been activated."""
    assert_target(target_commit)
    health = local_health(target_commit)
    if health.get("deliveryOwner") == "airflow_host":
        raise RuntimeError(
            "legacy rollback is unsafe after host delivery activation; use pause-host-delivery"
        )
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("ZACKS_OBSERVATION_MODE", "cloudflare")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "legacy")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    variable_set("WEBAPP_OBSERVATION_API_URL", LEGACY_OBSERVATION_URL)
    compose("up", "-d", "zacks-api", "zacks-notification-worker")
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "cloudflare",
        "rolledBack": True,
    }


def health(target_commit: str, *, include_public: bool) -> dict[str, Any]:
    assert_target(target_commit)
    local = local_health(target_commit)
    ready = local_ready()
    running = running_services()
    required = {"zacks-api", "zacks-notification-worker"}
    if not required.issubset(running):
        raise RuntimeError("one or more host-core services are not running")
    if local.get("deliveryOwner") != "airflow_host":
        raise RuntimeError("host notification delivery is not active")
    result: dict[str, Any] = {
        "targetCommit": target_commit,
        "local": local,
        "ready": ready,
        "services": sorted(required),
    }
    if include_public:
        result["public"] = public_health(target_commit)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate the Airflow-host Zacks notification core")
    parser.add_argument(
        "operation",
        choices=[
            "preflight",
            "deploy-shadow",
            "sync-secrets",
            "migrate",
            "enable-dual",
            "shadow-evidence",
            "prepare-cutover",
            "cutover",
            "pause-host-delivery",
            "health",
            "rollback",
        ],
    )
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--pass-name", default="manual")
    parser.add_argument("--include-public", action="store_true")
    arguments = parser.parse_args()

    operations = {
        "preflight": lambda: preflight(arguments.target_commit),
        "deploy-shadow": lambda: deploy_shadow(arguments.target_commit),
        "sync-secrets": lambda: sync_secrets(arguments.target_commit),
        "migrate": lambda: migrate(arguments.target_commit, pass_name=arguments.pass_name),
        "enable-dual": lambda: enable_dual(arguments.target_commit),
        "shadow-evidence": lambda: shadow_evidence(arguments.target_commit),
        "prepare-cutover": lambda: prepare_cutover(arguments.target_commit),
        "cutover": lambda: cutover(arguments.target_commit),
        "pause-host-delivery": lambda: pause_host_delivery(arguments.target_commit),
        "health": lambda: health(arguments.target_commit, include_public=arguments.include_public),
        "rollback": lambda: rollback(arguments.target_commit),
    }
    result = operations[arguments.operation]()
    print(
        json.dumps(
            {"success": True, "operation": arguments.operation, **result},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
