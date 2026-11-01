"""Python 3.6-compatible host procedure; application checks run in the pinned image.

Delivered over SSH stdin by recover_email_delivery.py. This module never checks
out code, builds/recreates a container, imports a database, or manufactures mail.
"""

import datetime
import json
import re
import subprocess
import sys
import time

API = "zacks-api"
MAIL = "zacks-notification-worker"
WECHAT = "zacks-wechat-worker"
SHA = re.compile(r"^[0-9a-f]{40}$")
CONTAINER = re.compile(r"^[0-9a-f]{12,64}$")
COMPOSE = ["docker", "compose", "-f", "docker-compose.yml"]


class RecoveryError(RuntimeError):
    pass


def run(command, input_text=None, timeout=40, allow_failure=False):
    options = {"stdin": subprocess.DEVNULL} if input_text is None else {"input": input_text}
    result = subprocess.run(  # noqa: UP022 -- host Python 3.6 has no capture_output
        command,
        universal_newlines=True,  # noqa: UP021 -- host Python 3.6 has no text argument
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        **options,
    )
    if result.returncode and not allow_failure:
        raise RecoveryError("bounded subprocess failed")
    return result.stdout.strip()


def timestamp(value):
    normalized = re.sub(r"([+-]\d\d):(\d\d)$", r"\1\2", str(value).replace("Z", "+0000"))
    pattern = "%Y-%m-%dT%H:%M:%S.%f%z" if "." in normalized else "%Y-%m-%dT%H:%M:%S%z"
    return datetime.datetime.strptime(normalized, pattern)


def container_info(service):
    ids = run(COMPOSE + ["ps", "--all", "--quiet", service]).splitlines()
    if len(ids) != 1 or not CONTAINER.fullmatch(ids[0]):
        raise RecoveryError("service must have exactly one existing container")
    # Raw inspect data never leaves this host: expose only identity/state below.
    data = json.loads(run(["docker", "inspect", ids[0]]))[0]
    environment = dict(value.split("=", 1) for value in data["Config"]["Env"] if "=" in value)
    labels = data["Config"].get("Labels") or {}
    if labels.get("com.docker.compose.service") != service:
        raise RecoveryError("container service ownership mismatch")
    return {
        "id": data["Id"],
        "image": data["Image"],
        "commit": environment.get("DEPLOYMENT_COMMIT"),
        "status": data["State"]["Status"],
        "command": data["Config"].get("Cmd"),
    }


def container_identity(expected, allow_api_stopped=False):
    if run(["git", "rev-parse", "HEAD"]) != expected:
        raise RecoveryError("host worktree identity changed")
    if run(["git", "status", "--porcelain", "--untracked-files=no"]):
        raise RecoveryError("host tracked files are modified")
    api, mail, wechat = [container_info(service) for service in (API, MAIL, WECHAT)]
    api_states = {"running", "exited"} if allow_api_stopped else {"running"}
    if api["status"] not in api_states or api["commit"] != expected or mail["commit"] != expected:
        raise RecoveryError("API or email runtime identity mismatch")
    if mail["image"] != api["image"]:
        raise RecoveryError("API and email worker must use the same immutable image")
    if mail["status"] not in {"running", "exited", "created"}:
        raise RecoveryError("email container is not safely startable")
    if wechat["status"] not in {"exited", "created"}:
        raise RecoveryError("email-only recovery requires the WeChat consumer stopped")
    if mail["command"] != ["python", "-m", "wechat_airflow.host_core.worker"]:
        raise RecoveryError("existing container is not the canonical email worker")
    image = json.loads(run(["docker", "image", "inspect", api["image"]]))[0]
    if (image["Config"].get("Labels") or {}).get("org.opencontainers.image.revision") != expected:
        raise RecoveryError("immutable image revision mismatch")
    return {"api": api, "mail": mail, "wechat": wechat}


def request_json(url):
    return json.loads(
        run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--max-time",
                "20",
                "--user-agent",
                "wechat-on-airflow-webapp-health/1.0",
                url,
            ]
        )
    )


def endpoint_checks(expected):
    local = request_json("http://127.0.0.1:8090/zacks-api/api/healthz")
    ready = request_json("http://127.0.0.1:8090/zacks-api/api/readyz")
    edge = request_json("https://courts.zacks.vision/api/edge-healthz")
    public = request_json("https://courts.zacks.vision/api/healthz")
    for value in (local, public):
        if value.get("ok") is not True or value.get("deploymentCommit") != expected:
            raise RecoveryError("host/public API health or identity mismatch")
        if value.get("runtime") != "airflow-host":
            raise RecoveryError("API does not have host ownership")
    if ready.get("ok") is not True or ready.get("emailReady") is not True:
        raise RecoveryError("email readiness failed")
    if not (
        edge.get("ok") is True
        and edge.get("deploymentCommit") == expected
        and edge.get("runtime") == "cloudflare-stateless-edge"
        and edge.get("cutover") is True
        and edge.get("quiesced") is False
        and edge.get("migrationEndpoint") is False
        and edge.get("durableBusinessState") == "none"
    ):
        raise RecoveryError("stateless edge identity or ownership mismatch")


def probe(options, identities, operation="snapshot", token="", since="", use_mail=False):
    service = identities["mail" if use_mail else "api"]["id"]
    raw = run(
        [
            "docker",
            "exec",
            "-i",
            service,
            "python",
            "-",
            options["runtimeCommit"],
            operation,
            token,
            since,
        ],
        input_text=options["probeSource"],
        timeout=70,
        allow_failure=True,
    )
    result = json.loads(raw)
    if result.get("ok") is not True:
        reason = result.get("reason", "application_guard_rejected")
        if not isinstance(reason, str) or not re.fullmatch(r"[a-z_]{1,100}", reason):
            reason = "application_guard_rejected"
        raise RecoveryError(reason)
    return result


def validate_snapshot(snapshot, expected):
    state = snapshot["state"]
    if not all(
        snapshot.get(key) is True
        for key in ("schemaReady", "emailConfiguration", "migrationComplete", "everActivated")
    ):
        raise RecoveryError("email recovery prerequisites are not satisfied")
    if state["deploymentCommit"] != expected or state["wechatEnabled"] is not False:
        raise RecoveryError("control identity or independent WeChat gate changed")
    if snapshot.get("freshVenueCount", 0) < 1:
        raise RecoveryError("no fresh healthy venue observations")


def fresh_heartbeat(snapshot, expected, since, active):
    heartbeat = snapshot.get("heartbeat") or {}
    try:
        at = timestamp(heartbeat["updatedAt"])
        age = (timestamp(snapshot["generatedAt"]) - at).total_seconds()
        after_start = at > timestamp(since)
    except (KeyError, TypeError, ValueError):
        return False
    return bool(
        heartbeat.get("healthy") is True
        and heartbeat.get("deploymentCommit") == expected
        and heartbeat.get("owner") is active
        and heartbeat.get("mode") == ("active" if active else "shadow")
        and after_start
        and 0 <= age < 120
    )


def assert_same_containers(original, current):
    for key in ("api", "mail", "wechat"):
        if (
            original[key]["id"] != current[key]["id"]
            or original[key]["image"] != current[key]["image"]
        ):
            raise RecoveryError("a concurrent operation replaced a container")


def wait_for_worker(options, identities, token, since, active):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        current = container_identity(options["runtimeCommit"])
        assert_same_containers(identities, current)
        if current["mail"]["status"] != "running":
            raise RecoveryError("email worker stopped during recovery")
        snapshot = probe(options, identities, since=since)
        validate_snapshot(snapshot, options["runtimeCommit"])
        if (
            snapshot["state"]["updatedAt"] != token
            or snapshot["state"]["deliveryEnabled"] is not active
        ):
            raise RecoveryError("delivery state changed during recovery")
        if fresh_heartbeat(snapshot, options["runtimeCommit"], since, active):
            return snapshot
        time.sleep(5)
    raise RecoveryError("email consumer did not produce the required fresh heartbeat")


def rollback(options, identities, before, enabled_token):
    """Fence only this recovery; never pause a later operator's activation."""
    try:
        current = container_identity(options["runtimeCommit"], allow_api_stopped=True)
        assert_same_containers(identities, current)
        use_mail = False
        try:
            state = probe(options, identities)["state"]
        except Exception:
            use_mail = True
            state = probe(options, identities, use_mail=True)["state"]
        if state["wechatEnabled"] is not False:
            return {"ok": False, "reason": "state_changed_no_rollback"}
        if enabled_token:
            if state["updatedAt"] != enabled_token or state["deliveryEnabled"] is not True:
                return {"ok": False, "reason": "state_changed_no_rollback"}
            probe(options, identities, "pause", enabled_token, use_mail=use_mail)
        elif (
            state["updatedAt"] != before["state"]["updatedAt"]
            or state["deliveryEnabled"] is not False
        ):
            return {"ok": False, "reason": "activation_result_uncertain_do_not_replay"}
        run(["docker", "stop", "--time", "40", identities["mail"]["id"]], timeout=50)
        return {"ok": True, "deliveryOwner": "paused", "existingMailContainerStopped": True}
    except Exception as exc:
        return {"ok": False, "reason": "rollback_incomplete", "errorClass": type(exc).__name__}


def recover(options):
    expected = options["runtimeCommit"]
    if not SHA.fullmatch(expected) or options["operation"] not in {"preflight", "resume", "status"}:
        raise RecoveryError("invalid bounded recovery request")
    identities = container_identity(expected)
    before = probe(options, identities)
    validate_snapshot(before, expected)
    endpoint_checks(expected)
    report = {
        "procedure": "email-delivery-recovery",
        "operation": options["operation"],
        "runtimeCommit": expected,
        "runtimeChanged": False,
        "wechatChanged": False,
        "fullReleaseAccepted": False,
        "syntheticNotifications": 0,
        "before": before,
    }
    if options["operation"] == "preflight":
        return {"ok": True, **report}
    if before["state"]["deliveryEnabled"] is True:
        # Repeated recovery is observation only: do not reset the window or restart.
        healthy = identities["mail"]["status"] == "running" and fresh_heartbeat(
            before, expected, before["state"]["updatedAt"], True
        )
        return {"ok": healthy, "alreadyActive": True, "after": before, **report}
    if options["operation"] == "status":
        return {"ok": False, "deliveryOwner": "paused", "after": before, **report}
    if identities["mail"]["status"] not in {"exited", "created"}:
        raise RecoveryError("paused recovery requires the existing email worker stopped")
    enabled_token = None
    try:
        # Start the existing container, with the external-delivery fence still closed.
        run(["docker", "start", identities["mail"]["id"]])
        wait_for_worker(
            options, identities, before["state"]["updatedAt"], before["generatedAt"], False
        )
        assert_same_containers(identities, container_identity(expected))
        enabled = probe(options, identities, "enable", before["state"]["updatedAt"])
        enabled_token = enabled["updatedAt"]
        after = wait_for_worker(options, identities, enabled_token, enabled_token, True)
        endpoint_checks(expected)
        return {
            "ok": True,
            "emailConsumerActive": True,
            "recoveryStartedAt": enabled_token,
            "after": after,
            **report,
        }
    except Exception as exc:
        return {
            "ok": False,
            "errorClass": type(exc).__name__,
            "reason": str(exc) if isinstance(exc, RecoveryError) else "unexpected_failure",
            "rollback": rollback(options, identities, before, enabled_token),
            **report,
        }


def main(options):
    try:
        report = recover(options)
    except Exception as exc:
        report = {
            "procedure": "email-delivery-recovery",
            "ok": False,
            "operation": options.get("operation"),
            "errorClass": type(exc).__name__,
            "reason": str(exc) if isinstance(exc, RecoveryError) else "unexpected_failure",
            "productionMutationAttempted": False,
        }
    print(json.dumps(report, sort_keys=True))
    if not report["ok"]:
        sys.exit(1)
