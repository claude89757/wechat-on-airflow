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
MIGRATION_DIRECTORY = ROOT / ".local" / "host-core-migration"


def run(command, check=True, capture=False, env=None, input_text=None):
    # Python 3.6 rejects even stdin=None when input is supplied. Omit the
    # mutually exclusive keyword entirely, while preserving EOF for commands
    # that must not consume the SSH session's standard input.
    input_options = {"stdin": subprocess.DEVNULL} if input_text is None else {"input": input_text}
    return subprocess.run(
        command,
        cwd=str(ROOT),
        check=check,
        universal_newlines=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env,
        **input_options,
    )


def compose(*arguments, **kwargs):
    env = kwargs.get("env")
    return run(COMPOSE + list(arguments), env=env)


def compose_exec(service, *arguments, **kwargs):
    capture = bool(kwargs.get("capture", False))
    check = bool(kwargs.get("check", True))
    user = kwargs.get("user")
    command = COMPOSE + ["exec", "-T"]
    if user:
        command += ["--user", str(user)]
    command += [service] + list(arguments)
    completed = run(command, check=check, capture=capture)
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
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--connect-timeout",
            "5",
            "--max-time",
            "15",
            url,
        ],
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


def _wait_for_local_ready(timeout_seconds=180):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            return local_ready()
        except Exception as exc:
            last_error = exc
            time.sleep(3)
    raise RuntimeError(f"host core did not become ready: {last_error}")


def application_environment(target_commit):
    environment = os.environ.copy()
    environment["DEPLOYMENT_COMMIT"] = target_commit
    environment["AIRFLOW_IMAGE_NAME"] = "wechat-on-airflow:host-" + target_commit
    return environment


def one_shot(script, target_commit, capture=True):
    completed = run(
        COMPOSE
        + ["run", "--rm", "--no-deps", "-T", "--entrypoint", "python", "zacks-api", "-c", script],
        capture=capture,
        env=application_environment(target_commit),
    )
    return completed.stdout.strip() if capture and completed.stdout else ""


def prepare_runtime(target_commit):
    result = preflight(target_commit)
    environment = application_environment(target_commit)
    os.environ.update(
        {key: environment[key] for key in ("DEPLOYMENT_COMMIT", "AIRFLOW_IMAGE_NAME")}
    )
    # Build before freezing the live edge; no provider secrets or business data leave the host.
    compose("build", "zacks-api", env=environment)
    secret_directory = Path(os.environ.get("AIRFLOW_SECRET_DIR", "/etc/wechat-on-airflow/secrets"))
    token = variable_get("WEBAPP_OBSERVATION_API_TOKEN")
    if len(token) < 16 or any(c.isspace() for c in token):
        raise RuntimeError("existing observation identity is invalid")
    token_path = secret_directory / "zacks_edge_token"
    if token_path.exists() and token_path.read_text().strip() != token:
        raise RuntimeError("existing edge identities disagree; refusing implicit rotation")
    if not token_path.exists():
        with token_path.open("w") as handle:
            handle.write(token + "\n")
        os.chmod(str(token_path), 0o640)
    state = _last_json(
        one_shot(
            "import json; from wechat_airflow.host_core.control import runtime_state; "
            "print(json.dumps(runtime_state(), default=str))",
            target_commit,
        )
    )
    backup_dir = ROOT / ".local" / "host-core-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(str(backup_dir), 0o700)
    backup = backup_dir / ("zacks-" + target_commit + ".dump")
    if not backup.exists():
        temporary = backup.with_suffix(".dump.tmp")
        with temporary.open("wb") as handle:
            completed = subprocess.run(
                COMPOSE
                + [
                    "exec",
                    "-T",
                    "postgresql",
                    "sh",
                    "-ec",
                    'export PGPASSWORD="$(cat /run/secrets/airflow_database_password)"; '
                    'exec pg_dump -U "$POSTGRESQL_USERNAME" -d "$POSTGRESQL_DATABASE" --schema=zacks --format=custom',
                ],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=subprocess.PIPE,
            )
        if completed.returncode != 0 or temporary.stat().st_size == 0:
            raise RuntimeError("pre-cutover business schema backup failed")
        os.chmod(str(temporary), 0o600)
        temporary.replace(backup)
    # The exclusive PG fence drains bounded in-flight sends. No old owner is reactivated.
    one_shot(
        "from wechat_airflow.host_core.control import set_delivery_enabled; "
        "set_delivery_enabled(False, %r)" % target_commit,
        target_commit,
    )
    compose("stop", "zacks-notification-worker", "zacks-wechat-worker", env=environment)
    one_shot(
        "from sqlalchemy import text; from wechat_airflow.host_core.database import transaction; "
        "c=transaction(); db=c.__enter__(); "
        'db.execute(text("UPDATE zacks.runtime_control SET deployment_started_at=now(), '
        "acceptance_started_at=NULL, wechat_enabled=false, phase='prepared', deployment_commit=:commit WHERE singleton\"), "
        "{'commit':%r}); c.__exit__(None,None,None)" % target_commit,
        target_commit,
    )
    compose("up", "-d", "--no-build", "--no-deps", "zacks-api", env=environment)
    _wait_for_local_health(target_commit)
    run([sys.executable, str(ROOT / "scripts/configure_zacks_tunnel.py"), "--apply", "--restart"])
    result.update(
        {
            "previouslyActivated": state.get("activated_at") is not None,
            "deliveryEnabled": False,
            "backupSha256": _sha256_file(backup),
            "backupCreated": True,
            "phase": "prepared",
        }
    )
    return result


def sync_secrets(target_commit):
    assert_target(target_commit)
    environment = os.environ.copy()
    environment["DEPLOYMENT_COMMIT"] = target_commit

    # Application image was built exactly once by prepare-runtime.
    edge_token = variable_get("WEBAPP_OBSERVATION_API_TOKEN")
    if len(edge_token) < 16 or any(character.isspace() for character in edge_token):
        raise RuntimeError("WEBAPP_OBSERVATION_API_TOKEN is malformed")

    stage_script = """
set -eu
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
            "--no-deps",
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
        "--no-deps",
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
            "--no-deps",
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
    runtime_uid = compose_exec("zacks-api", "id", "-u", capture=True)
    if not runtime_uid.isdigit():
        raise RuntimeError("zacks-api runtime UID is unavailable")
    compose("cp", str(source), f"zacks-api:{container_path}")
    try:
        compose_exec(
            "zacks-api",
            "chown",
            f"{runtime_uid}:0",
            container_path,
            user="0:0",
        )
        compose_exec(
            "zacks-api",
            "chmod",
            "0600",
            container_path,
            user="0:0",
        )
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
        compose_exec(
            "zacks-api",
            "rm",
            "-f",
            container_path,
            user="0:0",
            check=False,
        )

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


def prepare_routing(target_commit):
    assert_target(target_commit)
    # These variables only drain already-running old DAG tasks into the new API.
    # The new collector image has a fixed Compose-local destination.
    variable_set("WEBAPP_OBSERVATION_API_URL", LOCAL_OBSERVATION_URL)
    variable_set("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE", "enforce")
    compose_exec(
        "airflow-worker",
        "sh",
        "-ec",
        "rm -f /opt/airflow/logs/webapp-observation-state*.json /opt/airflow/logs/webapp-observation-state*.json.lock",
    )
    _wait_for_local_health(target_commit)
    _wait_for_local_ready()
    return {"targetCommit": target_commit, "observation": "host", "ready": True}


def cutover(target_commit):
    assert_target(target_commit)
    check_ses_credentials()
    host_python(
        "from wechat_airflow.host_core.control import set_delivery_enabled; "
        "set_delivery_enabled(True, %r)" % target_commit
    )
    compose(
        "up",
        "-d",
        "--no-build",
        "--no-deps",
        "zacks-notification-worker",
        "zacks-wechat-worker",
        env=application_environment(target_commit),
    )
    return {"targetCommit": target_commit, "deliveryOwner": "airflow_host", "legacyRuntime": False}


def pause_host_delivery(target_commit):
    assert_target(target_commit)
    one_shot(
        "from wechat_airflow.host_core.control import set_delivery_enabled; "
        "set_delivery_enabled(False, %r)" % target_commit,
        target_commit,
    )
    compose("stop", "zacks-notification-worker", "zacks-wechat-worker")
    return {
        "targetCommit": target_commit,
        "safePause": True,
        "deliveryOwner": "paused",
        "legacyRuntime": False,
    }


def activate_workers(target_commit):
    assert_target(target_commit)
    for component in (
        "airflow-api-server",
        "airflow-scheduler",
        "airflow-dag-processor",
        "airflow-worker",
        "airflow-triggerer",
    ):
        identity = compose_exec(
            component,
            "python",
            "-c",
            "import os; print(os.environ.get('DEPLOYMENT_COMMIT','unknown'))",
            capture=True,
        )
        if identity.splitlines()[-1] != target_commit:
            raise RuntimeError("runtime commit mismatch for " + component)
    sender = _last_json(
        host_python(
            "import json; from wechat_airflow.host_core.wechat_worker import sender_readiness; "
            "print(json.dumps(sender_readiness()))",
            capture=True,
        )
    )
    if (
        not sender.get("ok")
        or sender.get("deploymentCommit") != target_commit
        or not sender.get("durableIdempotency")
    ):
        raise RuntimeError("exact-commit durable WeChat sender is not ready")
    probe = _last_json(
        compose_exec(
            "zacks-api", "python", "-m", "wechat_airflow.host_core.api_probe", capture=True
        )
    )
    if probe.get("ok") is not True or probe.get("complete") is not True:
        raise RuntimeError("production API transaction probe failed")
    host_python(
        "from sqlalchemy import text; from wechat_airflow.host_core.database import transaction; "
        'c=transaction(); db=c.__enter__(); db.execute(text("UPDATE zacks.runtime_control SET api_acceptance=CAST(:value AS jsonb) WHERE singleton"), '
        + repr({"value": json.dumps(probe)})
        + "); c.__exit__(None,None,None)"
    )
    host_python(
        "from sqlalchemy import text; from wechat_airflow.host_core.database import transaction; "
        'c=transaction(); db=c.__enter__(); db.execute(text("UPDATE zacks.runtime_control '
        'SET wechat_enabled=true, acceptance_started_at=COALESCE(acceptance_started_at,now()) WHERE singleton")); c.__exit__(None,None,None)'
    )
    host_python(
        "from wechat_airflow.host_core.control import set_delivery_enabled; "
        "set_delivery_enabled(True, %r)" % target_commit
    )
    compose(
        "up",
        "-d",
        "--no-build",
        "--no-deps",
        "zacks-notification-worker",
        "zacks-wechat-worker",
        env=application_environment(target_commit),
    )
    return {"targetCommit": target_commit, "workersActivated": True, "legacyRuntime": False}


def health(target_commit, include_public=False, require_delivery=False):
    assert_target(target_commit)
    local = local_health(target_commit)
    ready = local_ready()
    arguments = [
        "python",
        "-m",
        "wechat_airflow.host_core.health",
        "--expected-commit",
        target_commit,
    ]
    if require_delivery:
        arguments.append("--require-delivery")
    completed = run(COMPOSE + ["exec", "-T", "zacks-api"] + arguments, check=False, capture=True)
    report = _last_json(completed.stdout or "")
    if report.get("complete") is not True or not report.get("checks"):
        raise RuntimeError("business acceptance report is incomplete")
    report["local"] = local
    report["ready"] = ready
    if include_public:
        report["public"] = public_health(target_commit)
        edge = _curl_json("https://zacks.claude89757.cc/api/edge-healthz")
        edge_ok = (
            edge.get("deploymentCommit") == target_commit
            and edge.get("legacyRuntime") is False
            and edge.get("cutover") is True
        )
        report["checks"]["pureEdgeExactCommit"] = edge_ok
        report["ok"] = report["ok"] and edge_ok
        report["edge"] = edge
    report["failedChecks"] = [name for name, ok in report["checks"].items() if not ok]
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Operate Host Core; legacy runtime is not supported"
    )
    parser.add_argument(
        "operation",
        choices=(
            "preflight",
            "prepare-runtime",
            "sync-secrets",
            "migrate-sql",
            "prepare-routing",
            "cutover",
            "activate-workers",
            "pause-host-delivery",
            "health",
            "acceptance",
        ),
    )
    parser.add_argument("--target-commit", required=True)
    parser.add_argument("--sql-export")
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--pass-name", default="final")
    parser.add_argument("--include-public", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()
    os.environ.update(
        {
            k: v
            for k, v in application_environment(args.target_commit).items()
            if k in ("DEPLOYMENT_COMMIT", "AIRFLOW_IMAGE_NAME")
        }
    )
    if args.operation == "migrate-sql":
        if not args.sql_export or not args.snapshot_sha256:
            parser.error("SQL export and checksum are required")
        result = migrate_sql(
            args.target_commit, args.pass_name, args.sql_export, args.snapshot_sha256
        )
    elif args.operation in ("health", "acceptance"):
        deadline = time.monotonic() + (args.wait_seconds if args.operation == "acceptance" else 0)
        while True:
            result = health(
                args.target_commit,
                include_public=args.include_public,
                require_delivery=args.operation == "acceptance",
            )
            if result["ok"] or time.monotonic() >= deadline:
                break
            print(
                json.dumps(
                    {
                        "event": "acceptance_progress",
                        "failedChecks": result["failedChecks"],
                        "naturalDelivery": result["naturalDelivery"],
                    }
                ),
                flush=True,
            )
            time.sleep(20)
    else:
        operations = {
            "preflight": preflight,
            "prepare-runtime": prepare_runtime,
            "sync-secrets": sync_secrets,
            "prepare-routing": prepare_routing,
            "cutover": cutover,
            "activate-workers": activate_workers,
            "pause-host-delivery": pause_host_delivery,
        }
        result = operations[args.operation](args.target_commit)
    success = result.get("ok", True)
    print(
        json.dumps(
            dict(result, operation=args.operation, success=success), default=str, ensure_ascii=False
        ),
        flush=True,
    )
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
