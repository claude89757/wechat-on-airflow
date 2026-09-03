#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
LOCAL_HEALTH = "http://127.0.0.1:8090/zacks-api/api/healthz"
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


def assert_target(target_commit: str) -> None:
    if len(target_commit) != 40 or any(character not in "0123456789abcdef" for character in target_commit.lower()):
        raise RuntimeError("target commit must be a full SHA")
    head = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    if head != target_commit:
        raise RuntimeError(f"worktree commit mismatch: expected {target_commit}, got {head}")


def variable_set(name: str, value: str) -> None:
    compose_exec("airflow-api-server", "airflow", "variables", "set", name, value)


def variable_get(name: str) -> str:
    return compose_exec(
        "airflow-api-server", "airflow", "variables", "get", name, capture=True
    )


def api_python(script: str, *, capture: bool = False) -> str:
    return compose_exec("zacks-api", "python", "-c", script, capture=capture)


def check_ses_credentials() -> None:
    api_python(
        "from wechat_airflow.host_core.settings import load_tencent_email_settings; "
        "load_tencent_email_settings(); print('ready')",
        capture=True,
    )


def local_health() -> dict[str, Any]:
    completed = run(
        ["curl", "--fail", "--silent", "--show-error", LOCAL_HEALTH],
        capture=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise RuntimeError("local host-core health check failed")
    return value


def public_health(expected_commit: str) -> dict[str, Any]:
    completed = run(
        ["curl", "--fail", "--silent", "--show-error", PUBLIC_HEALTH],
        capture=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict) or value.get("ok") is not True:
        raise RuntimeError("public host-core health check failed")
    if value.get("deploymentCommit") != expected_commit:
        raise RuntimeError("public host-core deployment identity mismatch")
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
    variable_set("ZACKS_OBSERVATION_MODE", "dual")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "legacy")
    compose("up", "-d", "--build", "zacks-api", "zacks-notification-worker", env=environment)
    run(
        [
            sys.executable,
            str(ROOT / "scripts" / "configure_zacks_tunnel.py"),
            "--apply",
            "--restart",
        ]
    )
    health = local_health()
    check_ses_credentials()
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
    result.update({"localHealth": health, "deliveryOwner": "cloudflare", "observation": "dual"})
    return result


def migrate(target_commit: str, *, pass_name: str) -> dict[str, Any]:
    assert_target(target_commit)
    snapshot_path = Path(tempfile.gettempdir()) / f"zacks-d1-{pass_name}-{target_commit}.json"
    try:
        output = compose_exec(
            "zacks-api",
            "python",
            "-m",
            "wechat_airflow.host_core.migration",
            "--source-revision",
            target_commit,
            "--snapshot-output",
            str(snapshot_path),
            capture=True,
        )
        result = json.loads(output.splitlines()[-1])
        if result.get("success") is not True:
            raise RuntimeError("host-core migration did not report success")
        return {"pass": pass_name, "counts": result.get("counts", {})}
    finally:
        snapshot_path.unlink(missing_ok=True)


def cutover(target_commit: str) -> dict[str, Any]:
    assert_target(target_commit)
    check_ses_credentials()
    variable_set("ZACKS_OBSERVATION_MODE", "host")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "host")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
    variable_set("ZACKS_DELIVERY_OWNER", "airflow_host")
    now_script = (
        "from sqlalchemy import text; "
        "from wechat_airflow.host_core.database import transaction; "
        "from wechat_airflow.host_core.domain import utc_now; "
        "c=transaction(); conn=c.__enter__(); "
        "conn.execute(text(\"UPDATE zacks.migration_state SET cutover_at=:now, updated_at=:now "
        "WHERE source='cloudflare-d1'\"), {'now': utc_now()}); c.__exit__(None,None,None)"
    )
    api_python(now_script)
    compose("restart", "zacks-api", "zacks-notification-worker")
    health = local_health()
    return {"targetCommit": target_commit, "deliveryOwner": "airflow_host", "localHealth": health}


def rollback(target_commit: str) -> dict[str, Any]:
    assert_target(target_commit)
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("ZACKS_OBSERVATION_MODE", "cloudflare")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "legacy")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    variable_set("WEBAPP_OBSERVATION_API_URL", LEGACY_OBSERVATION_URL)
    compose("restart", "zacks-api", "zacks-notification-worker")
    return {"targetCommit": target_commit, "deliveryOwner": "cloudflare", "rolledBack": True}


def health(target_commit: str, *, include_public: bool) -> dict[str, Any]:
    assert_target(target_commit)
    local = local_health()
    compose("ps", "--status", "running", "zacks-api", "zacks-notification-worker")
    result: dict[str, Any] = {"targetCommit": target_commit, "local": local}
    if include_public:
        result["public"] = public_health(target_commit)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Operate the Airflow-host Zacks notification core")
    parser.add_argument(
        "operation",
        choices=["preflight", "deploy-shadow", "migrate", "cutover", "health", "rollback"],
    )
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--pass-name", default="manual")
    parser.add_argument("--include-public", action="store_true")
    arguments = parser.parse_args()

    operations = {
        "preflight": lambda: preflight(arguments.target_commit),
        "deploy-shadow": lambda: deploy_shadow(arguments.target_commit),
        "migrate": lambda: migrate(arguments.target_commit, pass_name=arguments.pass_name),
        "cutover": lambda: cutover(arguments.target_commit),
        "health": lambda: health(arguments.target_commit, include_public=arguments.include_public),
        "rollback": lambda: rollback(arguments.target_commit),
    }
    result = operations[arguments.operation]()
    print(json.dumps({"success": True, "operation": arguments.operation, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
