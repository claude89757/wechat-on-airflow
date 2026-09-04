#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
LOCAL_HEALTH = "http://127.0.0.1:8090/zacks-api/api/healthz"
LOCAL_READY = "http://127.0.0.1:8090/zacks-api/api/readyz"
PUBLIC_HEALTH = "https://zacks.claude89757.cc/api/healthz"
LOCAL_OBSERVATION_URL = "http://zacks-api:8090/zacks-api/api/internal/observations"
LEGACY_OBSERVATION_URL = "https://zacks.claude89757.cc/api/internal/observations"
MIGRATION_DIRECTORY = ROOT / ".local" / "host-core-migration"


def run(command, check=True, capture=False, env=None, input_text=None):
    return subprocess.run(
        command,
        cwd=str(ROOT),
        check=check,
        universal_newlines=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
        input=input_text,
    )


def compose(*arguments, **kwargs):
    env = kwargs.get("env")
    return run(COMPOSE + list(arguments), env=env)


def compose_exec(service, *arguments, **kwargs):
    capture = bool(kwargs.get("capture", False))
    completed = run(
        COMPOSE + ["exec", "-T", service] + list(arguments),
        capture=capture,
    )
    return completed.stdout.strip() if capture and completed.stdout else ""


def running_services():
    return set(
        run(
            COMPOSE + ["ps", "--status", "running", "--services"],
            capture=True,
        ).stdout.splitlines()
    )


def assert_target(target_commit):
    if len(target_commit) != 40 or any(
        character not in "0123456789abcdef" for character in target_commit.lower()
    ):
        raise RuntimeError("target commit must be a full SHA")
    head = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    if head != target_commit:
        raise RuntimeError(f"worktree commit mismatch: expected {target_commit}, got {head}")


def variable_set(name, value):
    compose_exec("airflow-api-server", "airflow", "variables", "set", name, value)


def variable_get(name):
    output = compose_exec("airflow-api-server", "airflow", "variables", "get", name, capture=True)
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"Airflow Variable is unavailable: {name}")
    return lines[-1]


def host_python(script, capture=False):
    return compose_exec("zacks-api", "python", "-c", script, capture=capture)


def check_ses_credentials():
    result = host_python(
        "from wechat_airflow.host_core.settings import load_tencent_email_settings; "
        "load_tencent_email_settings(); print('ready')",
        capture=True,
    )
    if result.strip() != "ready":
        raise RuntimeError("host Tencent SES credentials are unavailable")


def _curl_json(url):
    completed = run(
        ["curl", "--fail", "--silent", "--show-error", url],
        capture=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError(f"health endpoint returned invalid JSON: {url}")
    return value


def _last_json(output):
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            value = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise RuntimeError("operation returned no structured JSON result")


def _sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _migration_source(value):
    source = Path(value)
    if not source.is_absolute():
        source = ROOT / source
    source = source.resolve()
    migration_root = MIGRATION_DIRECTORY.resolve()
    try:
        common = os.path.commonpath([str(source), str(migration_root)])
    except ValueError:
        common = ""
    if common != str(migration_root):
        raise RuntimeError(f"SQL migration source must be inside {migration_root}")
    if not source.is_file():
        raise RuntimeError(f"SQL migration source does not exist: {source}")
    return source


def local_health(expected_commit=None):
    value = _curl_json(LOCAL_HEALTH)
    if value.get("ok") is not True:
        raise RuntimeError("local host-core health check failed")
    if expected_commit and value.get("deploymentCommit") != expected_commit:
        raise RuntimeError("local host-core deployment identity mismatch")
    return value


def local_ready():
    value = _curl_json(LOCAL_READY)
    if value.get("ok") is not True:
        raise RuntimeError("local host-core readiness check failed")
    return value


def public_health(expected_commit):
    value = _curl_json(PUBLIC_HEALTH)
    if value.get("ok") is not True:
        raise RuntimeError("public host-core health check failed")
    if value.get("deploymentCommit") != expected_commit:
        raise RuntimeError("public host-core deployment identity mismatch")
    if value.get("runtime") != "airflow-host":
        raise RuntimeError("public API is not routed to the Airflow-host runtime")
    return value


def preflight(target_commit):
    assert_target(target_commit)
    compose("config", "--quiet")
    disk = os.statvfs(str(ROOT))
    free_bytes = disk.f_bavail * disk.f_frsize
    if free_bytes < 8000000000:
        raise RuntimeError("less than 8 GB is available on the reliable repository filesystem")
    run([sys.executable, str(ROOT / "scripts" / "configure_zacks_tunnel.py")])
    return {
        "targetCommit": target_commit,
        "compose": "valid",
        "freeBytes": free_bytes,
        "tunnelPlan": "valid",
        "hostPython": sys.version.split()[0],
    }


def _wait_for_local_health(target_commit, timeout_seconds=180):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            return local_health(target_commit)
        except Exception as exc:
            last_error = exc
            time.sleep(3)
    raise RuntimeError(f"host core did not become healthy: {last_error}")


def deploy_shadow(target_commit):
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
    health_value = _wait_for_local_health(target_commit)
    ready_value = local_ready()
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
            "localHealth": health_value,
            "localReady": ready_value,
            "deliveryOwner": "cloudflare",
            "observation": "cloudflare",
        }
    )
    return result


def sync_secrets(target_commit):
    assert_target(target_commit)
    environment = os.environ.copy()
    environment["DEPLOYMENT_COMMIT"] = target_commit

    compose("--profile", "maintenance", "build", "zacks-secret-sync", env=environment)
    edge_token = variable_get("WEBAPP_OBSERVATION_API_TOKEN")
    if len(edge_token) < 16 or any(character.isspace() for character in edge_token):
        raise RuntimeError("WEBAPP_OBSERVATION_API_TOKEN is malformed")

    stage_script = """
set -euo pipefail
umask 027
target=/etc/wechat-on-airflow/secrets/zacks_edge_token
temporary=${target}.tmp.$$
trap 'rm -f "$temporary"' EXIT
cat > "$temporary"
test -s "$temporary"
chmod 0640 "$temporary"
mv -f "$temporary" "$target"
trap - EXIT
"""
    run(
        COMPOSE
        + [
            "--profile",
            "maintenance",
            "run",
            "--rm",
            "-T",
            "--entrypoint",
            "sh",
            "zacks-secret-sync",
            "-ec",
            stage_script,
        ],
        env=environment,
        input_text=edge_token + "\n",
    )

    completed = compose(
        "--profile",
        "maintenance",
        "run",
        "--rm",
        "zacks-secret-sync",
        env=environment,
    )
    validation = run(
        COMPOSE
        + [
            "--profile",
            "maintenance",
            "run",
            "--rm",
            "-T",
            "--entrypoint",
            "python",
            "zacks-secret-sync",
            "-c",
            (
                "from wechat_airflow.host_core.settings import "
                "load_settings, load_tencent_email_settings; "
                "assert load_settings().edge_token; "
                "load_tencent_email_settings(); print('ready')"
            ),
        ],
        capture=True,
        env=environment,
    )
    if not validation.stdout or validation.stdout.strip().splitlines()[-1] != "ready":
        raise RuntimeError("host-core secret validation failed")
    return {
        "targetCommit": target_commit,
        "secretSync": "complete",
        "edgeToken": "staged",
        "returnCode": completed.returncode,
    }


def migrate(target_commit, pass_name):
    """Legacy migration endpoint path retained for rollback diagnostics only."""
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
    result = _last_json(host_python(script, capture=True))
    if result.get("success") is not True:
        raise RuntimeError("host-core migration did not report success")
    return {
        "targetCommit": target_commit,
        "pass": pass_name,
        "source": "worker-pagination",
        "counts": result.get("counts", {}),
    }


def migrate_sql(target_commit, pass_name, sql_export, snapshot_sha256):
    assert_target(target_commit)
    source = _migration_source(sql_export)
    actual_sha256 = _sha256_file(source)
    if not snapshot_sha256:
        raise RuntimeError("snapshot SHA-256 is required")
    if actual_sha256 != snapshot_sha256.lower():
        raise RuntimeError(
            f"host SQL export checksum mismatch: expected {snapshot_sha256}, got {actual_sha256}"
        )

    container_path = "/tmp/zacks-d1-{}-{}.sql.gz".format(
        pass_name.replace("/", "-"), actual_sha256[:16]
    )
    compose("cp", str(source), f"zacks-api:{container_path}")
    try:
        output = compose_exec(
            "zacks-api",
            "python",
            "/opt/airflow/project/scripts/import_d1_sql_export.py",
            "--sql-export",
            container_path,
            "--source-revision",
            target_commit,
            "--expected-sha256",
            actual_sha256,
            capture=True,
        )
    finally:
        compose_exec("zacks-api", "rm", "-f", container_path)

    result = _last_json(output)
    if result.get("success") is not True:
        raise RuntimeError("host-core SQL migration did not report success")
    if result.get("sha256") != actual_sha256:
        raise RuntimeError("container SQL export checksum mismatch")
    return {
        "targetCommit": target_commit,
        "pass": pass_name,
        "source": "d1-control-plane-sql-export",
        "snapshotSha256": actual_sha256,
        "counts": result.get("imported") or result.get("counts") or {},
    }


def enable_dual(target_commit):
    assert_target(target_commit)
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("ZACKS_OBSERVATION_MODE", "dual")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "legacy")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
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


def shadow_evidence(target_commit):
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
    evidence = _last_json(host_python(script, capture=True))
    if int(evidence.get("totalVenues") or 0) != 26:
        raise RuntimeError("host-core venue catalog is incomplete")
    if int(evidence.get("recentVenues") or 0) < 20:
        raise RuntimeError("fewer than 20 venues naturally reseeded the host-core runtime")
    if int(evidence.get("activeSubscriptions") or 0) <= 0:
        raise RuntimeError("host-core migration contains no active subscriptions")
    result = {"targetCommit": target_commit}
    result.update(evidence)
    return result


def prepare_cutover(target_commit):
    assert_target(target_commit)
    check_ses_credentials()
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
    variable_set("ZACKS_OBSERVATION_MODE", "host")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "host")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    compose("stop", "zacks-notification-worker")
    compose("restart", "zacks-api")
    health_value = local_health(target_commit)
    ready_value = local_ready()
    if health_value.get("deliveryOwner") != "cloudflare":
        raise RuntimeError("delivery must remain paused before public edge cutover")
    if health_value.get("observationMode") != "host":
        raise RuntimeError("host observation mode did not activate before edge cutover")
    if "zacks-notification-worker" in running_services():
        raise RuntimeError("notification worker is still running during delivery pause")
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "cloudflare",
        "observation": "host",
        "notificationWorker": "stopped",
        "localHealth": health_value,
        "localReady": ready_value,
    }


def cutover(target_commit):
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
    health_value = local_health(target_commit)
    ready_value = local_ready()
    if health_value.get("deliveryOwner") != "airflow_host":
        raise RuntimeError("local delivery owner did not switch to airflow_host")
    if "zacks-notification-worker" not in running_services():
        raise RuntimeError("host notification worker did not start")
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "airflow_host",
        "localHealth": health_value,
        "localReady": ready_value,
    }


def pause_host_delivery(target_commit):
    assert_target(target_commit)
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
    variable_set("ZACKS_OBSERVATION_MODE", "host")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "host")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    compose("stop", "zacks-notification-worker")
    health_value = local_health(target_commit)
    ready_value = local_ready()
    if health_value.get("deliveryOwner") != "cloudflare":
        raise RuntimeError("host delivery did not enter the safe paused state")
    if "zacks-notification-worker" in running_services():
        raise RuntimeError("notification worker remains active after safe pause")
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "cloudflare",
        "observation": "host",
        "notificationWorker": "stopped",
        "safePause": True,
        "localHealth": health_value,
        "localReady": ready_value,
    }


def rollback(target_commit):
    assert_target(target_commit)
    owner = variable_get("ZACKS_DELIVERY_OWNER").lower()
    if owner == "airflow_host":
        raise RuntimeError(
            "legacy rollback is unsafe after host delivery activation; use pause-host-delivery"
        )
    variable_set("ZACKS_DELIVERY_OWNER", "cloudflare")
    variable_set("ZACKS_OBSERVATION_MODE", "cloudflare")
    variable_set("ZACKS_WECHAT_GATE_SOURCE", "legacy")
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    variable_set("WEBAPP_OBSERVATION_API_URL", LEGACY_OBSERVATION_URL)
    compose("stop", "zacks-notification-worker", "zacks-api")
    return {
        "targetCommit": target_commit,
        "deliveryOwner": "cloudflare",
        "hostServices": "stopped",
        "rolledBack": True,
    }


def health(target_commit, include_public):
    assert_target(target_commit)
    local = local_health(target_commit)
    ready = local_ready()
    running = running_services()
    required = {"zacks-api", "zacks-notification-worker"}
    if not required.issubset(running):
        raise RuntimeError("one or more host-core services are not running")
    if local.get("deliveryOwner") != "airflow_host":
        raise RuntimeError("host notification delivery is not active")
    result = {
        "targetCommit": target_commit,
        "local": local,
        "ready": ready,
        "services": sorted(required),
    }
    if include_public:
        result["public"] = public_health(target_commit)
    return result


def main():
    parser = argparse.ArgumentParser(description="Operate the Airflow-host Zacks notification core")
    parser.add_argument(
        "operation",
        choices=(
            "preflight",
            "deploy-shadow",
            "sync-secrets",
            "migrate",
            "migrate-sql",
            "enable-dual",
            "shadow-evidence",
            "prepare-cutover",
            "cutover",
            "pause-host-delivery",
            "health",
            "rollback",
        ),
    )
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--pass-name", default="manual")
    parser.add_argument("--sql-export")
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--include-public", action="store_true")
    arguments = parser.parse_args()

    if arguments.operation == "preflight":
        result = preflight(arguments.target_commit)
    elif arguments.operation == "deploy-shadow":
        result = deploy_shadow(arguments.target_commit)
    elif arguments.operation == "sync-secrets":
        result = sync_secrets(arguments.target_commit)
    elif arguments.operation == "migrate":
        result = migrate(arguments.target_commit, arguments.pass_name)
    elif arguments.operation == "migrate-sql":
        if not arguments.sql_export or not arguments.snapshot_sha256:
            raise RuntimeError("migrate-sql requires --sql-export and --snapshot-sha256")
        result = migrate_sql(
            arguments.target_commit,
            arguments.pass_name,
            arguments.sql_export,
            arguments.snapshot_sha256,
        )
    elif arguments.operation == "enable-dual":
        result = enable_dual(arguments.target_commit)
    elif arguments.operation == "shadow-evidence":
        result = shadow_evidence(arguments.target_commit)
    elif arguments.operation == "prepare-cutover":
        result = prepare_cutover(arguments.target_commit)
    elif arguments.operation == "cutover":
        result = cutover(arguments.target_commit)
    elif arguments.operation == "pause-host-delivery":
        result = pause_host_delivery(arguments.target_commit)
    elif arguments.operation == "health":
        result = health(arguments.target_commit, arguments.include_public)
    elif arguments.operation == "rollback":
        result = rollback(arguments.target_commit)
    else:
        raise RuntimeError("unsupported operation")

    payload = {"success": True, "operation": arguments.operation}
    payload.update(result)
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
