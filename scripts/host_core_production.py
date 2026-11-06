#!/usr/bin/env python3
import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("HOST_CORE_ROOT") or Path(__file__).resolve().parents[1])
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]
LOCAL_HEALTH = "http://127.0.0.1:8090/zacks-api/api/healthz"
LOCAL_READY = "http://127.0.0.1:8090/zacks-api/api/readyz"
PUBLIC_HEALTH = "https://zacks.claude89757.cc/api/healthz"
LOCAL_OBSERVATION_URL = "http://zacks-api:8090/zacks-api/api/internal/observations"
MIGRATION_DIRECTORY = ROOT / ".local" / "host-core-migration"
RECOVERY_DIRECTORY = ROOT / ".local" / "host-core-recovery"
RECOVERY_COMPONENTS = (
    "zacks-api",
    "zacks-notification-worker",
    "zacks-wechat-worker",
    "airflow-api-server",
    "airflow-scheduler",
    "airflow-dag-processor",
    "airflow-worker",
    "airflow-triggerer",
)

# This bounded program runs in the existing Python 3.12 API container. It never
# calls transaction()/ensure_schema(), and never changes an Outbox or a receipt.
RECOVERY_PROBE = r"""
import json
import os
import sys
from datetime import UTC, datetime
from sqlalchemy import text
from wechat_airflow.host_core.control import DELIVERY_LOCK
from wechat_airflow.host_core.database import SCHEMA_REVISION, get_engine
from wechat_airflow.host_core.release_checkpoint import migration_reconciled
from wechat_airflow.host_core.settings import load_tencent_email_settings

def require(value, reason):
    if not value:
        raise ValueError(reason)

def timestamp(value):
    return value.astimezone(UTC).isoformat() if value is not None else None

def probe(options):
    expected = options["runtimeCommit"]
    require(os.environ.get("DEPLOYMENT_COMMIT") == expected, "runtime_identity_changed")
    stamp = datetime.fromisoformat(options["updatedAt"].replace("Z", "+00:00"))
    require(stamp.tzinfo is not None, "control_timezone_missing")
    load_tencent_email_settings()
    with get_engine().begin() as connection:
        if options["operation"] == "fence":
            connection.execute(text("SET LOCAL lock_timeout = '300s'"))
            connection.execute(text("SET LOCAL statement_timeout = '310s'"))
            connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DELIVERY_LOCK})
        else:
            connection.execute(text("SET TRANSACTION READ ONLY"))
            connection.execute(text("SET LOCAL statement_timeout = '20s'"))
        require(connection.execute(text("SELECT to_regclass('zacks.schema_versions')")).scalar_one() is not None, "schema_missing")
        require(connection.execute(text("SELECT EXISTS (SELECT 1 FROM zacks.schema_versions WHERE version=:revision)"), {"revision": SCHEMA_REVISION}).scalar_one() is True, "schema_fingerprint_missing")
        state = connection.execute(text("SELECT deployment_commit, delivery_enabled, wechat_enabled, activated_at, updated_at, phase FROM zacks.runtime_control WHERE singleton" + (" FOR UPDATE" if options["operation"] == "fence" else ""))).mappings().one()
        require(state["deployment_commit"] == expected, "control_identity_changed")
        require(state["updated_at"] == stamp, "control_timestamp_changed")
        require(state["delivery_enabled"] is True and state["wechat_enabled"] is False and state["phase"] == "active", "recovery_gate_baseline_changed")
        require(state["activated_at"] is not None, "never_activated")
        migration = connection.execute(text("SELECT imported_at, details FROM zacks.migration_state WHERE source='cloudflare-d1'")).mappings().first()
        require(migration and migration["imported_at"] is not None and migration_reconciled(migration["details"]), "migration_checkpoint_invalid")
        heartbeat = connection.execute(text("SELECT deployment_commit, healthy, updated_at, details FROM zacks.runtime_heartbeats WHERE component='zacks-notification-worker'")).mappings().one()
        now = datetime.now(UTC)
        details = heartbeat["details"] if isinstance(heartbeat["details"], dict) else {}
        if options["operation"] == "snapshot":
            require(heartbeat["deployment_commit"] == expected and heartbeat["healthy"] is True and details.get("owner") is True and details.get("mode") == "active" and 0 <= (now - heartbeat["updated_at"]).total_seconds() < 120, "active_mail_heartbeat_missing")
        result = {"ok": True, "schemaRevision": SCHEMA_REVISION, "everActivated": True, "migrationComplete": True, "generatedAt": timestamp(now), "state": {"deploymentCommit": state["deployment_commit"], "deliveryEnabled": state["delivery_enabled"], "wechatEnabled": state["wechat_enabled"], "activatedAt": timestamp(state["activated_at"]), "updatedAt": timestamp(state["updated_at"]), "phase": state["phase"]}, "heartbeat": {"deploymentCommit": heartbeat["deployment_commit"], "healthy": heartbeat["healthy"] is True, "updatedAt": timestamp(heartbeat["updated_at"]), "owner": details.get("owner") is True, "mode": "active" if details.get("mode") == "active" else "other"}}
        if options["operation"] == "fence":
            updated = connection.execute(text("UPDATE zacks.runtime_control SET delivery_enabled=false, wechat_enabled=false, phase='prepared', deployment_commit=:target, deployment_started_at=now(), acceptance_started_at=NULL, updated_at=now() WHERE singleton AND deployment_commit=:expected AND updated_at=:stamp AND delivery_enabled=true AND wechat_enabled=false RETURNING updated_at"), {"target": options["targetCommit"], "expected": expected, "stamp": stamp}).scalar_one()
            result["fencedAt"] = timestamp(updated)
        return result

try:
    print(json.dumps(probe(json.loads(sys.argv[1])), sort_keys=True))
except Exception as error:
    # Database/transport exceptions may contain credentials. Publish a reason
    # only when it is one of the fixed guard codes above.
    payload = {"ok": False, "errorClass": type(error).__name__}
    reason = str(error)
    if reason.isidentifier() and reason.islower() and len(reason) <= 80:
        payload["reason"] = reason
    print(json.dumps(payload))
    raise SystemExit(1) from None
"""


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


def verify_existing_configuration():
    """Routine upgrades verify existing ingress/routing; never repair it implicitly."""
    result = _last_json(
        run([sys.executable, str(ROOT / "scripts/configure_zacks_tunnel.py")], capture=True).stdout
    )
    if result.get("changed") is not False or result.get("applied") is not False:
        raise RuntimeError("existing tunnel configuration differs; explicit repair required")
    if variable_get("WEBAPP_OBSERVATION_API_URL") != LOCAL_OBSERVATION_URL:
        raise RuntimeError("existing observation route differs; explicit repair required")
    if variable_get("WEBAPP_WECHAT_SUBSCRIPTION_GATE_MODE") != "enforce":
        raise RuntimeError("existing subscription gate differs; explicit repair required")


def already_activated():
    state = _last_json(
        host_python(
            "import json; from wechat_airflow.host_core.control import runtime_state; "
            "print(json.dumps(runtime_state(), default=str))",
            capture=True,
        )
    )
    return state.get("activated_at") is not None


def routine_preflight(target_commit):
    """Validate the current live installation without building or activating a candidate."""
    result = preflight(target_commit)
    checkpoint = _last_json(
        host_python(
            "import json,os; from wechat_airflow.host_core.release_checkpoint import read_checkpoint; "
            "print(json.dumps(read_checkpoint(os.environ['DEPLOYMENT_COMMIT'])))",
            capture=True,
        )
    )
    current_commit = checkpoint.get("deploymentCommit")
    if (
        not isinstance(current_commit, str)
        or len(current_commit) != 40
        or any(character not in "0123456789abcdef" for character in current_commit)
    ):
        raise RuntimeError("routine upgrade requires a valid live runtime identity")
    if (
        checkpoint.get("everActivated") is not True
        or checkpoint.get("migrationComplete") is not True
    ):
        raise RuntimeError("routine upgrade requires an activated, verified migration checkpoint")
    delivery = checkpoint.get("deliveryEnabled")
    wechat = checkpoint.get("wechatEnabled")
    # A full pause can roll forward, because shipping a fix may be the only way out.
    # Activating this release turns delivery back on. Delivery on with WeChat off is
    # the email recovery mode, which keeps its own recovery-upgrade path.
    if type(delivery) is not bool or type(wechat) is not bool or (delivery and not wechat):
        raise RuntimeError("routine upgrade requires full delivery or a full pause")
    token = variable_get("WEBAPP_OBSERVATION_API_TOKEN")
    token_path = (
        Path(os.environ.get("AIRFLOW_SECRET_DIR", "/etc/wechat-on-airflow/secrets"))
        / "zacks_edge_token"
    )
    if not token_path.is_file() or token_path.read_text().strip() != token or len(token) < 16:
        raise RuntimeError(
            "existing edge identity missing or inconsistent; explicit repair required"
        )
    verify_existing_configuration()
    local_health(checkpoint.get("deploymentCommit"))
    local_ready()
    result.update(
        {
            "routineUpgrade": True,
            "deliveryWasPaused": not delivery,
            "existingConfigurationPreserved": True,
            "currentDeploymentCommit": checkpoint.get("deploymentCommit"),
            "migrationComplete": True,
            "everActivated": True,
        }
    )
    return result


def _recovery_timestamp(value):
    normalized = re.sub(r"([+-]\d\d):(\d\d)$", r"\1\2", str(value).replace("Z", "+0000"))
    pattern = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in normalized else "%Y-%m-%dT%H:%M:%S%z"
    return datetime.datetime.strptime(normalized, pattern)


def recovery_arguments(runtime_commit, updated_at, delivery_enabled, wechat_enabled, baseline_file):
    if not re.fullmatch(r"[0-9a-f]{40}", runtime_commit or ""):
        raise RuntimeError("recovery requires the exact existing runtime commit")
    if delivery_enabled != "true" or wechat_enabled != "false":
        raise RuntimeError("recovery accepts only the explicit email-active WeChat-paused baseline")
    _recovery_timestamp(updated_at)
    path = Path(baseline_file or "")
    if not path.is_absolute():
        path = ROOT / path
    if (
        path.parent.resolve() != RECOVERY_DIRECTORY.resolve()
        or not re.fullmatch(r"[0-9a-f]{40}-[0-9]+-[0-9]+\.json", path.name)
        or path.is_symlink()
    ):
        raise RuntimeError("recovery baseline must use the protected evidence directory")
    return {"runtimeCommit": runtime_commit, "updatedAt": updated_at, "baselineFile": str(path)}


def _require_recovery_runtime_images(containers, expected):
    """The stopped WeChat consumer is not a delivery owner and may still be old.

    Recovery replaces that container after the fence. Requiring its image to
    already match the live API blocks the only path that can start it again.
    A running WeChat consumer, and the live API and email worker, must match.
    """
    api = containers["zacks-api"]
    for service in ("zacks-api", "zacks-notification-worker", "zacks-wechat-worker"):
        current = containers[service]
        if service == "zacks-wechat-worker" and current["status"] in {"exited", "created"}:
            continue
        if current["commit"] != expected or current["image"] != api["image"]:
            raise RuntimeError("recovery Host Core images differ from the expected runtime")


def _recovery_instances():
    instances = []
    for service in RECOVERY_COMPONENTS:
        identifiers = sorted(
            run(COMPOSE + ["ps", "--all", "--quiet", service], capture=True).stdout.splitlines()
        )
        expected_count = 2 if service == "airflow-scheduler" else 1
        if (
            len(identifiers) != expected_count
            or len(set(identifiers)) != expected_count
            or any(not re.fullmatch(r"[0-9a-f]{12,64}", item) for item in identifiers)
        ):
            raise RuntimeError("recovery_container_replica_count_mismatch")
        instances.extend((service, identifier) for identifier in identifiers)
    return instances


def _recovery_containers(expected):
    containers = {}
    for service, identifier in _recovery_instances():
        raw = json.loads(run(["docker", "inspect", identifier], capture=True).stdout)[0]
        labels = raw["Config"].get("Labels") or {}
        environment = dict(value.split("=", 1) for value in raw["Config"]["Env"] if "=" in value)
        commit = environment.get("DEPLOYMENT_COMMIT", "")
        if labels.get("com.docker.compose.service") != service or not re.fullmatch(
            r"[0-9a-f]{40}", commit
        ):
            raise RuntimeError("recovery container ownership or runtime identity invalid")
        stopped = service == "zacks-wechat-worker"
        if raw["State"]["Status"] not in ({"exited", "created"} if stopped else {"running"}):
            raise RuntimeError("recovery container state changed")
        image = json.loads(run(["docker", "image", "inspect", raw["Image"]], capture=True).stdout)[
            0
        ]
        if (image["Config"].get("Labels") or {}).get("org.opencontainers.image.revision") != commit:
            raise RuntimeError("recovery image revision does not match its container")
        key = service + ":" + identifier if service == "airflow-scheduler" else service
        containers[key] = {
            "id": raw["Id"],
            "image": raw["Image"],
            "commit": commit,
            "status": raw["State"]["Status"],
        }
        if service in {"zacks-notification-worker", "zacks-wechat-worker"}:
            module = "worker" if service == "zacks-notification-worker" else "wechat_worker"
            if raw["Config"].get("Cmd") != ["python", "-m", "wechat_airflow.host_core." + module]:
                raise RuntimeError("recovery consumer command differs from the canonical worker")
    _require_recovery_runtime_images(containers, expected)
    # A second Compose project must not silently become a second delivery owner.
    running_mail = run(
        [
            "docker",
            "ps",
            "--no-trunc",
            "--quiet",
            "--filter",
            "label=com.docker.compose.service=zacks-notification-worker",
        ],
        capture=True,
    ).stdout.splitlines()
    if running_mail != [containers["zacks-notification-worker"]["id"]]:
        raise RuntimeError("recovery requires a single running email container")
    running_wechat = run(
        [
            "docker",
            "ps",
            "--quiet",
            "--filter",
            "label=com.docker.compose.service=zacks-wechat-worker",
        ],
        capture=True,
    ).stdout.strip()
    if running_wechat:
        raise RuntimeError("recovery requires all WeChat consumers stopped")
    return containers


def _recovery_probe(options, containers, operation="snapshot", target_commit=None):
    payload = {
        "runtimeCommit": options["runtimeCommit"],
        "updatedAt": options["updatedAt"],
        "operation": operation,
        "targetCommit": target_commit,
    }
    completed = run(
        ["docker", "exec", "-i", containers["zacks-api"]["id"], "python", "-", json.dumps(payload)],
        capture=True,
        check=False,
        input_text=RECOVERY_PROBE,
    )
    result = _last_json(completed.stdout or "")
    if completed.returncode or result.get("ok") is not True:
        reason = result.get("reason")
        if isinstance(reason, str) and _public_recovery_reason(RuntimeError(reason)) == reason:
            raise RuntimeError(reason)
        raise RuntimeError("recovery database identity, checkpoint, gate or heartbeat guard failed")
    return result


def recovery_snapshot(options, expected_source, require_health=True):
    assert_target(expected_source)
    if run(["git", "status", "--porcelain", "--untracked-files=no"], capture=True).stdout.strip():
        raise RuntimeError("recovery refuses a modified production worktree")
    containers = _recovery_containers(options["runtimeCommit"])
    evidence = _recovery_probe(
        options, containers, operation="snapshot" if require_health else "identity"
    )
    if require_health:
        local_health(options["runtimeCommit"])
        local_ready()
        public_health(options["runtimeCommit"])
        edge = _curl_json("https://zacks.claude89757.cc/api/edge-healthz")
        if not (
            edge.get("ok") is True
            and edge.get("deploymentCommit") == options["runtimeCommit"]
            and edge.get("runtime") == "cloudflare-stateless-edge"
            and edge.get("cutover") is True
            and edge.get("legacyRuntime") is False
            and edge.get("quiesced") is False
            and edge.get("durableBusinessState") == "none"
        ):
            raise RuntimeError("recovery requires the matching stateless production edge")
        verify_existing_configuration()
    return {"containers": containers, **evidence}


def capture_recovery_baseline(target_commit, recovery):
    if target_commit == recovery["runtimeCommit"]:
        raise RuntimeError("recovery upgrade requires a repaired new commit")
    snapshot = recovery_snapshot(recovery, recovery["runtimeCommit"])
    path = Path(recovery["baselineFile"])
    if path.parent.is_symlink():
        raise RuntimeError("recovery evidence directory must not be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(str(path.parent), 0o700)
    baseline = {
        "evidenceVersion": 1,
        "targetCommit": target_commit,
        "sourceCommit": recovery["runtimeCommit"],
        **snapshot,
    }
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(baseline, handle, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    return {"ok": True, "baselineCaptured": True, "baselineSha256": _sha256_file(path), **baseline}


def _verify_recovery_baseline(target_commit, recovery, source_commit, require_health=True):
    path = Path(recovery["baselineFile"])
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise RuntimeError("recovery evidence permissions are unsafe")
    baseline = json.loads(path.read_text())
    if (
        baseline.get("evidenceVersion") != 1
        or baseline.get("targetCommit") != target_commit
        or baseline.get("sourceCommit") != recovery["runtimeCommit"]
    ):
        raise RuntimeError("recovery evidence identity mismatch")
    snapshot = recovery_snapshot(recovery, source_commit, require_health=require_health)
    for key in ("containers", "schemaRevision", "state"):
        if snapshot[key] != baseline[key]:
            raise RuntimeError("recovery baseline changed after capture")
    return {
        "ok": True,
        "recoveryUpgrade": True,
        "targetCommit": target_commit,
        "baselineSha256": _sha256_file(path),
        **snapshot,
    }


def recovery_preflight(target_commit, recovery):
    return _verify_recovery_baseline(target_commit, recovery, target_commit)


def prepare_recovery_source(target_commit, recovery):
    _verify_recovery_baseline(target_commit, recovery, recovery["runtimeCommit"])
    run(["git", "fetch", "--quiet", "--prune", "origin", "main"])
    if run(["git", "rev-parse", "origin/main"], capture=True).stdout.strip() != target_commit:
        raise RuntimeError("recovery target is no longer current main")
    run(["git", "checkout", "--quiet", "--detach", target_commit])
    assert_target(target_commit)
    return {
        "ok": True,
        "sourcePrepared": True,
        "previousCommit": recovery["runtimeCommit"],
        "targetCommit": target_commit,
    }


def restore_recovery_source(target_commit, recovery):
    # Missing runner output alone never proves that a remote fence did not commit.
    # Verify the complete live identity/control baseline before source-only undo.
    current = run(["git", "rev-parse", "HEAD"], capture=True).stdout.strip()
    if current == recovery["runtimeCommit"]:
        _verify_recovery_baseline(target_commit, recovery, current, require_health=False)
        return {
            "ok": True,
            "sourceRestored": False,
            "runtimeUnchanged": True,
            "targetCommit": target_commit,
        }
    _verify_recovery_baseline(target_commit, recovery, target_commit, require_health=False)
    run(["git", "checkout", "--quiet", "--detach", recovery["runtimeCommit"]])
    assert_target(recovery["runtimeCommit"])
    return {
        "ok": True,
        "sourceRestored": True,
        "runtimeUnchanged": True,
        "targetCommit": target_commit,
    }


def recovery_candidate_schema(target_commit, expected_revision):
    image = json.loads(
        run(
            ["docker", "image", "inspect", "wechat-on-airflow:host-" + target_commit], capture=True
        ).stdout
    )[0]
    if (image["Config"].get("Labels") or {}).get(
        "org.opencontainers.image.revision"
    ) != target_commit:
        raise RuntimeError("recovery candidate image identity mismatch")
    output = one_shot(
        "import json; from sqlalchemy import text; from wechat_airflow.host_core.database import get_engine,SCHEMA_REVISION; c=get_engine().connect(); ready=c.execute(text('SELECT EXISTS (SELECT 1 FROM zacks.schema_versions WHERE version=:revision)'), {'revision':SCHEMA_REVISION}).scalar_one(); c.close(); print(json.dumps({'schemaReady':ready,'schemaRevision':SCHEMA_REVISION}))",
        target_commit,
    )
    value = _last_json(output)
    if value.get("schemaReady") is not True or value.get("schemaRevision") != expected_revision:
        raise RuntimeError("recovery cannot apply a new business schema revision")


def prepare_runtime(target_commit, routine_only=False, recovery=None):
    if routine_only and recovery is not None:
        raise RuntimeError("routine and recovery upgrade modes are mutually exclusive")
    if routine_only:
        routine_preflight(target_commit)
    recovery_evidence = (
        recovery_preflight(target_commit, recovery) if recovery is not None else None
    )
    result = preflight(target_commit)
    environment = application_environment(target_commit)
    os.environ.update(
        {key: environment[key] for key in ("DEPLOYMENT_COMMIT", "AIRFLOW_IMAGE_NAME")}
    )
    # Build before freezing the live edge; no provider secrets or business data leave the host.
    compose("build", "zacks-api", env=environment)
    if recovery_evidence is not None:
        recovery_candidate_schema(target_commit, recovery_evidence["schemaRevision"])
    secret_directory = Path(os.environ.get("AIRFLOW_SECRET_DIR", "/etc/wechat-on-airflow/secrets"))
    token = variable_get("WEBAPP_OBSERVATION_API_TOKEN")
    if len(token) < 16 or any(c.isspace() for c in token):
        raise RuntimeError("existing observation identity is invalid")
    token_path = secret_directory / "zacks_edge_token"
    if token_path.exists() and token_path.read_text().strip() != token:
        raise RuntimeError("existing edge identities disagree; refusing implicit rotation")
    state = (
        {"activated_at": recovery_evidence["state"]["activatedAt"]}
        if recovery_evidence is not None
        else _last_json(
            one_shot(
                "import json; from wechat_airflow.host_core.control import runtime_state; "
                "print(json.dumps(runtime_state(), default=str))",
                target_commit,
            )
        )
    )
    routine_upgrade = state.get("activated_at") is not None
    if routine_only and not routine_upgrade:
        raise RuntimeError("routine upgrade cannot initialize an unactivated installation")
    if routine_upgrade:
        if not token_path.exists():
            raise RuntimeError("existing edge identity missing; explicit repair required")
        verify_existing_configuration()
    if not token_path.exists():
        with token_path.open("w") as handle:
            handle.write(token + "\n")
        os.chmod(str(token_path), 0o640)
    backup_dir = ROOT / ".local" / "host-core-backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(str(backup_dir), 0o700)
    backup = backup_dir / ("zacks-" + target_commit + ".dump")
    if (
        recovery is not None
        and backup.exists()
        and (backup.is_symlink() or backup.stat().st_size == 0 or backup.stat().st_mode & 0o077)
    ):
        raise RuntimeError("recovery refuses an unsafe or empty existing backup")
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
    # Recovery must distinguish guard failures from a partially mutated runtime.
    if recovery is not None:
        recovery_evidence = recovery_preflight(target_commit, recovery)
    # The exclusive PG fence drains bounded in-flight sends. No old owner is reactivated.
    if recovery is not None:
        _recovery_probe(
            recovery,
            recovery_evidence["containers"],
            operation="fence",
            target_commit=target_commit,
        )
        # A rejected CAS must not trigger a pause of another operator's state.
        # If the connection is lost after commit, the database fence is already closed.
        print(json.dumps({"event": "host_runtime_mutation_started"}), flush=True)
    else:
        print(json.dumps({"event": "host_runtime_mutation_started"}), flush=True)
        one_shot(
            "from wechat_airflow.host_core.control import set_delivery_enabled; "
            "set_delivery_enabled(False, %r)" % target_commit,
            target_commit,
        )
    compose("stop", "zacks-notification-worker", "zacks-wechat-worker", env=environment)
    if recovery is None:
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
    if not routine_upgrade:
        run(
            [
                sys.executable,
                str(ROOT / "scripts/configure_zacks_tunnel.py"),
                "--apply",
                "--restart",
            ]
        )
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


def prepare_routing(target_commit, routine_only=False):
    assert_target(target_commit)
    if already_activated():
        verify_existing_configuration()
        _wait_for_local_health(target_commit)
        _wait_for_local_ready()
        return {
            "targetCommit": target_commit,
            "observation": "host",
            "ready": True,
            "existingConfigurationPreserved": True,
            "cachesPreserved": True,
        }
    if routine_only:
        raise RuntimeError("routine upgrade cannot initialize routing")
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
            "import json; from wechat_airflow.host_core.wechat_worker import "
            "SENDER_PROTOCOL_VERSION, sender_readiness; "
            "print(json.dumps({**sender_readiness(), 'expectedProtocol': SENDER_PROTOCOL_VERSION}))",
            capture=True,
        )
    )
    if (
        not sender.get("ok")
        or sender.get("protocolVersion") != sender.get("expectedProtocol")
        or not sender.get("durableIdempotency")
    ):
        raise RuntimeError("compatible durable WeChat sender is not ready")
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


NATURAL_DELIVERY_CHECKS = {"naturalEmailProviderDelivered", "naturalWeChatDelivered"}
NATURAL_OBSERVATION_CHECKS = NATURAL_DELIVERY_CHECKS | {"allNaturalDagCycles"}
# Missing evidence is not evidence of technical health. Keep this floor aligned
# with the complete v1 business-health report; additional checks still apply.
REQUIRED_ACCEPTANCE_CHECKS = (
    {
        "exactHostCommit",
        "exactControlCommit",
        "acceptanceWindowStarted",
        "singleHostDeliveryOwner",
        "wechatDeliveryEnabled",
        "subscriptionApiTransaction",
        "emailConfiguration",
        "migrationReconciled",
        "zacks-notification-worker",
        "zacks-wechat-worker",
        "all26VenueObservations",
        "allObservationScopesHealthy",
        "allNaturalDagCycles",
        "allRequiredDagsUnpaused",
        "wechatEnqueueIncidentsResolved",
        "senderReady",
        "senderProtocolCompatible",
        "senderDurableIdempotency",
        "senderTransportNotCloudflareProxied",
        "pureEdgeExactCommit",
    }
    | NATURAL_DELIVERY_CHECKS
    | {
        table + ":" + check
        for table in ("notification_outbox", "system_email_outbox", "wechat_outbox")
        for check in ("noNewUnknownSubmission", "noNewTerminalFailure", "noStalledBacklog")
    }
)


def acceptance_status(report):
    # complete describes report completeness, NOT successful business acceptance.
    checks = report.get("checks")
    if (
        report.get("complete") is not True
        or report.get("schemaVersion") != 1
        or report.get("errors")
        or report.get("error")
        or not isinstance(checks, dict)
        or not REQUIRED_ACCEPTANCE_CHECKS.issubset(checks)
        or any(type(value) is not bool for value in checks.values())
    ):
        return "failed"
    failed = {name for name, passed in checks.items() if not passed}
    if report.get("failedChecks") != [name for name, passed in checks.items() if not passed]:
        return "failed"
    if not failed and report.get("ok") is True:
        return "accepted"
    if failed and failed.issubset(NATURAL_OBSERVATION_CHECKS) and report.get("ok") is False:
        return "pending"
    return "failed"


def main():
    parser = argparse.ArgumentParser(
        description="Operate Host Core; legacy runtime is not supported"
    )
    parser.add_argument(
        "operation",
        choices=(
            "preflight",
            "routine-preflight",
            "capture-recovery-baseline",
            "prepare-recovery-source",
            "recovery-preflight",
            "restore-recovery-source",
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
    parser.add_argument("--routine-only", action="store_true")
    parser.add_argument("--recovery-runtime-commit", default="")
    parser.add_argument("--recovery-control-updated-at", default="")
    parser.add_argument("--recovery-delivery-enabled", choices=("true", "false"), default="false")
    parser.add_argument("--recovery-wechat-enabled", choices=("true", "false"), default="false")
    parser.add_argument("--recovery-baseline-file", default="")
    parser.add_argument("--sql-export")
    parser.add_argument("--snapshot-sha256")
    parser.add_argument("--pass-name", default="final")
    parser.add_argument("--include-public", action="store_true")
    parser.add_argument("--wait-seconds", type=int, default=1800)
    args = parser.parse_args()
    recovery = None
    recovery_operations = {
        "capture-recovery-baseline",
        "prepare-recovery-source",
        "recovery-preflight",
        "restore-recovery-source",
    }
    if args.recovery_runtime_commit:
        if args.operation not in recovery_operations | {"prepare-runtime"} or args.routine_only:
            parser.error("recovery inputs are limited to the explicit recovery lifecycle")
        recovery = recovery_arguments(
            args.recovery_runtime_commit,
            args.recovery_control_updated_at,
            args.recovery_delivery_enabled,
            args.recovery_wechat_enabled,
            args.recovery_baseline_file,
        )
        if not re.fullmatch(r"[0-9a-f]{40}", args.target_commit) or not Path(
            recovery["baselineFile"]
        ).name.startswith(args.target_commit + "-"):
            parser.error("recovery evidence must be bound to the exact target commit")
    elif (
        args.operation in recovery_operations
        or args.recovery_baseline_file
        or args.recovery_control_updated_at
        or args.recovery_delivery_enabled != "false"
        or args.recovery_wechat_enabled != "false"
    ):
        parser.error("complete explicit recovery inputs are required")
    os.environ.update(
        {
            k: v
            for k, v in application_environment(args.target_commit).items()
            if k in ("DEPLOYMENT_COMMIT", "AIRFLOW_IMAGE_NAME")
        }
    )
    if args.routine_only and args.operation not in ("prepare-runtime", "prepare-routing"):
        parser.error("routine-only is limited to runtime and routing preparation")
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
            "routine-preflight": routine_preflight,
            "capture-recovery-baseline": capture_recovery_baseline,
            "prepare-recovery-source": prepare_recovery_source,
            "recovery-preflight": recovery_preflight,
            "restore-recovery-source": restore_recovery_source,
            "prepare-runtime": prepare_runtime,
            "sync-secrets": sync_secrets,
            "prepare-routing": prepare_routing,
            "cutover": cutover,
            "activate-workers": activate_workers,
            "pause-host-delivery": pause_host_delivery,
        }
        if args.operation in recovery_operations:
            result = operations[args.operation](args.target_commit, recovery)
        elif args.operation == "prepare-runtime" and recovery is not None:
            result = prepare_runtime(args.target_commit, recovery=recovery)
        elif args.operation in ("prepare-runtime", "prepare-routing"):
            result = operations[args.operation](args.target_commit, routine_only=args.routine_only)
        else:
            result = operations[args.operation](args.target_commit)
    status = acceptance_status(result) if args.operation == "acceptance" else None
    if status is not None:
        result["acceptanceStatus"] = status
    success = status == "accepted" if status is not None else result.get("ok", True)
    print(
        json.dumps(
            dict(result, operation=args.operation, success=success), default=str, ensure_ascii=False
        ),
        flush=True,
    )
    return 75 if status == "pending" else (0 if success else 1)


def _public_recovery_reason(error):
    """Return a fixed guard name. Never forward database or transport text."""
    message = str(error)
    if message.isidentifier() and message.islower() and len(message) <= 80:
        return message
    if message in {
        "recovery Host Core images differ from the expected runtime",
        "recovery consumer command differs from the canonical worker",
        "recovery image revision does not match its container",
        "recovery container ownership or runtime identity invalid",
        "recovery container state changed",
        "recovery requires one existing container per component",
        "recovery requires a single running email container",
        "recovery requires all WeChat consumers stopped",
        "recovery refuses a modified production worktree",
        "recovery upgrade requires a repaired new commit",
        "recovery requires the matching stateless production edge",
        "recovery database identity, checkpoint, gate or heartbeat guard failed",
        "local host-core health check failed",
        "local host-core deployment identity mismatch",
        "local host-core readiness check failed",
        "public host-core health check failed",
        "public host-core deployment identity mismatch",
        "public API is not routed to the Airflow-host runtime",
        "existing tunnel configuration differs; explicit repair required",
        "existing observation route differs; explicit repair required",
        "existing subscription gate differs; explicit repair required",
        "target commit must be a full SHA",
    }:
        return message
    return None


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        if "--recovery-runtime-commit" not in sys.argv:
            raise
        payload = {
            "ok": False,
            "success": False,
            "errorClass": type(error).__name__,
            "replaySafe": False,
        }
        reason = _public_recovery_reason(error)
        if reason is not None:
            payload["reason"] = reason
        print(json.dumps(payload), flush=True)
        raise SystemExit(1) from None
