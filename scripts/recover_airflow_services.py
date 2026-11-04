#!/usr/bin/env python3
"""Start stopped Airflow application containers without changing the deployed commit."""

from __future__ import annotations

import argparse
import inspect
import json
import re
from typing import Any

from _ops import OpsError, airflow_remote, emit, run, ssh_command
from production_health import ssh_failure_detail

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
MUTATING_ACTIONS = {"start", "restart", "create"}


def recovery_action(container):
    status = str(container.get("status") or "")
    health = str(container.get("health") or "")
    restarts = int(container.get("restart_count") or 0)
    oom = bool(container.get("oom_killed"))
    if not container.get("id"):
        return "create"
    if oom and restarts >= 3:
        return "report"
    if status == "restarting":
        return "report"
    if status == "running" and health == "starting":
        return "wait"
    if status == "running" and health == "unhealthy":
        return "restart"
    if status == "running":
        return "keep"
    if status in {"exited", "created", "dead"}:
        return "start"
    return "report"


def origin_blocked_action(action, origin_status):
    if action == "keep" and origin_status != 200:
        return "restart"
    return action


def tunnel_action(active_state, public_statuses, load_state="loaded"):
    if str(load_state or "") != "loaded":
        return "report"
    state = str(active_state or "")
    if state in {"activating", "reloading"}:
        return "wait"
    codes = list(public_statuses or [])
    if state == "active" and codes and all(code == 200 for code in codes):
        return "keep"
    if state != "active":
        return "restart"
    if any(code in (None, 530) for code in codes) or not codes:
        return "restart"
    return "keep"


def redact_text(value):
    text = str(value or "")
    text = re.sub(
        r"(?i)(password|secret|token|authorization|fernet|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=<redacted>",
        text,
    )
    text = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "<redacted-email>", text)
    text = re.sub(r"\b(?:postgres(?:ql)?|redis|mysql|amqp)://\S+", "<redacted-url>", text)
    return text


def plan_actions(inventory, origin_status):
    start_order = (
        "airflow-api-server",
        "airflow-scheduler",
        "airflow-dag-processor",
        "airflow-triggerer",
        "airflow-worker",
        "zacks-notification-worker",
        "zacks-wechat-worker",
    )
    blocked = []
    for name in ("postgresql", "redis"):
        rows = inventory.get(name) or []
        if not any(item.get("status") == "running" for item in rows):
            blocked.append(name)
    anchor_ready = any(
        item.get("status") == "running" for item in (inventory.get("zacks-api") or [])
    )
    if not anchor_ready:
        blocked.append("zacks-api")
    planned = []
    for service in start_order:
        rows = list(inventory.get(service) or [])
        if service == "airflow-api-server" and len(rows) > 1:
            chosen = max(
                rows,
                key=lambda item: item.get("finished_at") or item.get("started_at") or "",
            )
            for extra in rows:
                if extra is not chosen:
                    planned.append(
                        {
                            "service": service,
                            "id": extra.get("id") or "",
                            "action": "report",
                            "reason": "duplicate",
                        }
                    )
            rows = [chosen]
        if not rows:
            action = "report" if blocked else "create"
            planned.append({"service": service, "id": "", "action": action})
            continue
        for container in rows:
            action = recovery_action(container)
            if service == "airflow-api-server":
                action = origin_blocked_action(action, origin_status)
            if blocked and action in MUTATING_ACTIONS:
                action = "report"
            planned.append(
                {
                    "service": service,
                    "id": container.get("id") or "",
                    "action": action,
                }
            )
    return {
        "anchor_ready": anchor_ready,
        "blocked_data_services": blocked,
        "actions": planned,
    }


def remote_script() -> str:
    helpers = "\n\n".join(
        inspect.getsource(function)
        for function in (
            recovery_action,
            origin_blocked_action,
            tunnel_action,
            redact_text,
            plan_actions,
        )
    )
    body = """set -eu
repo_path="$1"
cd "$repo_path"
python3 - "$repo_path" <<'PY'
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

__HELPERS__
MUTATING_ACTIONS = {"start", "restart", "create"}
repo_path = sys.argv[1]
os.chdir(repo_path)


def run_command(args, check=True):
    result = subprocess.run(
        args,
        cwd=repo_path,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        message = redact_text(result.stderr.strip() or result.stdout.strip() or "command failed")
        raise RuntimeError(message[:500])
    return result


def service_ids(service):
    filters = [
        ["docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=wechat-on-airflow"],
        ["docker", "ps", "-aq"],
    ]
    for command in filters:
        result = run_command(command + ["--filter", f"label=com.docker.compose.service={service}"])
        found = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if found:
            return found
    return []


def inspected(container_id):
    payload = json.loads(run_command(["docker", "inspect", container_id]).stdout)[0]
    state = payload.get("State") or {}
    health = (state.get("Health") or {}).get("Status") or ""
    return {
        "id": container_id,
        "status": state.get("Status") or "",
        "health": health,
        "restart_count": int(state.get("RestartCount") or 0),
        "oom_killed": bool(state.get("OOMKilled")),
        "exit_code": state.get("ExitCode"),
        "error": redact_text(str(state.get("Error") or ""))[:300],
        "started_at": state.get("StartedAt") or "",
        "finished_at": state.get("FinishedAt") or "",
    }


def origin_status():
    request = urllib.request.Request(
        "http://127.0.0.1:8080/api/v2/monitor/health",
        headers={"User-Agent": "wechat-on-airflow-service-recover/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.getcode()
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def log_tail(container_id):
    result = run_command(["docker", "logs", "--tail", "60", container_id], check=False)
    text = redact_text((result.stdout or "") + "\\n" + (result.stderr or ""))
    return "\\n".join(text.splitlines()[-60:])[:4000]


def sibling_runtime():
    for service in ("zacks-api", "airflow-scheduler", "airflow-dag-processor"):
        for container_id in service_ids(service):
            payload = json.loads(run_command(["docker", "inspect", container_id]).stdout)[0]
            if (payload.get("State") or {}).get("Status") != "running":
                continue
            image = (payload.get("Config") or {}).get("Image") or ""
            commit = ""
            for item in (payload.get("Config") or {}).get("Env") or []:
                if item.startswith("DEPLOYMENT_COMMIT="):
                    commit = item.split("=", 1)[1]
            secret_dir = ""
            for mount in payload.get("Mounts") or []:
                if mount.get("Destination") == "/etc/wechat-on-airflow/secrets":
                    secret_dir = mount.get("Source") or ""
            if image and re.fullmatch(r"[0-9a-f]{40}", commit) and secret_dir:
                return image, commit, secret_dir
    raise RuntimeError("no running sibling container provides the deployed image")


def create_service(service):
    image, commit, secret_dir = sibling_runtime()
    env = os.environ.copy()
    env["AIRFLOW_IMAGE_NAME"] = image
    env["DEPLOYMENT_COMMIT"] = commit
    env["AIRFLOW_SECRET_DIR"] = secret_dir
    result = subprocess.run(
        ["docker", "compose", "up", "-d", "--no-deps", "--no-build", service],
        cwd=repo_path,
        env=env,
        universal_newlines=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise RuntimeError(redact_text(result.stderr or result.stdout)[:500])


def apply_action(service, container, action):
    container_id = container.get("id") or ""
    if action in {"keep", "wait", "report"}:
        return action
    if action == "start":
        run_command(["docker", "start", container_id])
        return "started"
    if action == "restart":
        run_command(["docker", "restart", "-t", "20", container_id])
        return "restarted"
    if action == "create":
        create_service(service)
        return "created"
    raise RuntimeError("unsupported recovery action")


def wait_origin():
    deadline = time.time() + 300
    status = origin_status()
    while status != 200 and time.time() < deadline:
        time.sleep(5)
        status = origin_status()
    return status


TUNNEL_UNIT = "cloudflared.service"
TUNNEL_PUBLIC_URLS = (
    "https://airflow.claude89757.cc/api/v2/monitor/health",
    "https://airflow.claude89757.cc/zacks-api/api/healthz",
)


def http_status(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "wechat-on-airflow-service-recover/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.getcode()
    except urllib.error.HTTPError as exc:
        return exc.code
    except Exception:
        return None


def tunnel_fields():
    result = run_command(
        [
            "systemctl",
            "show",
            TUNNEL_UNIT,
            "--property=LoadState,ActiveState,SubState,UnitFileState,NRestarts,Result",
        ],
        check=False,
    )
    fields = {}
    for line in result.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value.strip()
    if result.returncode and not fields:
        fields["error"] = redact_text(result.stderr.strip() or result.stdout.strip())[:200]
    return fields


def recover_tunnel():
    try:
        before_fields = tunnel_fields()
        active = before_fields.get("ActiveState") or ""
        before_public = [http_status(url) for url in TUNNEL_PUBLIC_URLS]
        action = tunnel_action(active, before_public, before_fields.get("LoadState") or "")
        outcome = action
        if action == "restart":
            run_command(["systemctl", "restart", TUNNEL_UNIT])
            outcome = "restarted"
        after_public = before_public
        if action in {"restart", "wait"}:
            deadline = time.time() + 90
            while not all(code == 200 for code in after_public) and time.time() < deadline:
                time.sleep(5)
                after_public = [http_status(url) for url in TUNNEL_PUBLIC_URLS]
        after_fields = tunnel_fields()
        return {
            "unit": TUNNEL_UNIT,
            "action": action,
            "result": outcome,
            "active_before": active,
            "active_after": after_fields.get("ActiveState") or "",
            "load_state": after_fields.get("LoadState") or "",
            "unit_file_state": after_fields.get("UnitFileState") or "",
            "n_restarts": after_fields.get("NRestarts") or "",
            "service_result": after_fields.get("Result") or "",
            "public_before": before_public,
            "public_after": after_public,
        }
    except Exception as exc:
        return {
            "unit": TUNNEL_UNIT,
            "action": "restart",
            "result": "error",
            "error": redact_text(str(exc))[:300],
            "public_before": [],
            "public_after": [],
        }


def container_for(inventory, service, container_id):
    for item in inventory.get(service) or []:
        if item.get("id") == container_id:
            return item
    return {"id": container_id}


try:
    head_before = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()
    watched = (
        "airflow-api-server",
        "airflow-scheduler",
        "airflow-dag-processor",
        "airflow-triggerer",
        "airflow-worker",
        "zacks-notification-worker",
        "zacks-wechat-worker",
        "postgresql",
        "redis",
        "zacks-api",
    )
    inventory = {
        service: [inspected(container_id) for container_id in service_ids(service)]
        for service in watched
    }
    before = origin_status()
    plan = plan_actions(inventory, before)
    results = []
    log_tails = []

    def perform(item):
        container = container_for(inventory, item["service"], item["id"])
        if item["action"] in MUTATING_ACTIONS | {"report"} and container.get("id"):
            log_tails.append(
                {
                    "service": item["service"],
                    "id": container["id"][:12],
                    "text": log_tail(container["id"]),
                }
            )
        try:
            outcome = apply_action(item["service"], container, item["action"])
            results.append({**item, "result": outcome})
        except Exception as exc:
            results.append(
                {
                    **item,
                    "result": "error",
                    "error": redact_text(str(exc))[:300],
                }
            )

    api_items = [item for item in plan["actions"] if item["service"] == "airflow-api-server"]
    for item in api_items:
        perform(item)
    api_failed = any(
        item["service"] == "airflow-api-server"
        and (item["action"] == "report" or item.get("result") == "error")
        for item in results
    )
    after = before
    if not api_failed:
        needs_origin = any(
            item["service"] == "airflow-api-server" and item["action"] in MUTATING_ACTIONS | {"wait"}
            for item in plan["actions"]
        )
        after = wait_origin() if needs_origin or before != 200 else before
        if after == 200:
            for item in plan["actions"]:
                if item["service"] != "airflow-api-server":
                    perform(item)
    else:
        after = origin_status()
    head_after = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()
    api_now = [inspected(container_id) for container_id in service_ids("airflow-api-server")]
    tunnel = recover_tunnel()
    public_after = tunnel.get("public_after") or []
    tunnel_ok = (
        tunnel.get("result") != "error"
        and bool(public_after)
        and all(code == 200 for code in public_after)
    )
    summary = {
        service: [
            {
                "id": item["id"][:12],
                "status": item["status"],
                "health": item["health"],
                "restart_count": item["restart_count"],
                "oom_killed": item["oom_killed"],
                "exit_code": item["exit_code"],
            }
            for item in rows
        ]
        for service, rows in inventory.items()
    }
    ok = (
        after == 200
        and head_before == head_after
        and not plan["blocked_data_services"]
        and any(item.get("status") == "running" for item in api_now)
        and not any(item.get("result") == "error" for item in results)
        and not any(
            item["service"] == "airflow-api-server" and item["action"] == "report" for item in results
        )
        and tunnel_ok
    )
    payload = {
        "ok": ok,
        "applied": any(item.get("result") in {"started", "restarted", "created"} for item in results),
        "host_commit": head_after,
        "commit_unchanged": head_before == head_after,
        "database_unchanged": True,
        "origin_health_before": before,
        "origin_health_after": after,
        "tunnel": tunnel,
        "blocked_data_services": plan["blocked_data_services"],
        "actions": results,
        "services": summary,
        "log_tails": log_tails,
        "api_server_after": [
            {"id": item["id"][:12], "status": item["status"], "health": item["health"]}
            for item in api_now
        ],
    }
except Exception as exc:
    payload = {
        "ok": False,
        "applied": False,
        "database_unchanged": True,
        "commit_unchanged": None,
        "error_type": type(exc).__name__,
        "error": redact_text(str(exc))[:500],
    }
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
raise SystemExit(0 if payload.get("ok") else 1)
PY
"""
    return body.replace("__HELPERS__", helpers)


def parse_remote_result(output: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise OpsError("Airflow service recovery did not return a structured result")


def tunnel_restored(payload: dict[str, Any]) -> bool:
    tunnel = payload.get("tunnel") if isinstance(payload.get("tunnel"), dict) else {}
    public_after = tunnel.get("public_after") or []
    return (
        tunnel.get("result") != "error"
        and bool(public_after)
        and all(code == 200 for code in public_after)
    )


def recovery_succeeded(payload: dict[str, Any]) -> bool:
    return (
        payload.get("ok") is True
        and payload.get("origin_health_after") == 200
        and payload.get("commit_unchanged") is True
        and payload.get("database_unchanged") is True
        and payload.get("blocked_data_services") == []
        and tunnel_restored(payload)
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Start stopped Airflow application containers on the current host checkout."
    )
    parser.add_argument("--operation-commit", required=True)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    if not COMMIT_PATTERN.fullmatch(args.operation_commit):
        raise OpsError("operation commit must be a full SHA-1")

    remote = airflow_remote()
    command = ssh_command(remote)
    command[1:1] = ["-o", "LogLevel=ERROR"]
    result = run(
        [*command, "bash", "-s", "--", remote["repository_path"]],
        check=False,
        input_text=remote_script(),
    )
    payload: dict[str, Any] = {}
    if result.stdout.strip():
        try:
            payload = parse_remote_result(result.stdout)
        except OpsError:
            payload = {}
    if payload:
        payload["operation_commit"] = args.operation_commit
        emit(payload, args.format)
    if result.returncode or not recovery_succeeded(payload):
        if payload and payload.get("origin_health_after") == 200 and not tunnel_restored(payload):
            raise OpsError("Airflow service recovery did not restore the public tunnel")
        if payload:
            raise OpsError("Airflow service recovery did not restore the API origin")
        raise OpsError(
            ssh_failure_detail(result.stderr, result.stdout) or "Airflow service recovery failed"
        )


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"recover-airflow-services: {exc}")
        raise SystemExit(1) from exc
