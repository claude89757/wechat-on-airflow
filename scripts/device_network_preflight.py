#!/usr/bin/env python3
"""Read-only migration inventory. Never export runtime configuration or send notifications."""

from __future__ import annotations

import argparse
import http.client
import json
import logging
import os
import re
import shlex
import subprocess
from typing import Any

from _ops import REPO_ROOT, OpsError, airflow_remote, emit, run, ssh_command

SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_RESPONSE_BYTES = 65536
HOST_PROBE = r"""
import json
import os
import re
from urllib.parse import urlsplit
import requests
from sqlalchemy import text
from wechat_airflow.host_core.database import transaction
from wechat_airflow.host_core.settings import _first_value

report = {"runtimeCommit": os.environ.get("DEPLOYMENT_COMMIT"), "externalTestSends": 0}
for label, url in (("api", "http://127.0.0.1:8090/api/healthz"),
                   ("sender", _first_value("WECHAT_SEND_API_URL") or "")):
    try:
        if label == "sender":
            parsed = urlsplit(url)
            url = parsed._replace(path="/readyz", query="", fragment="").geturl()
        response = requests.get(url, timeout=20, allow_redirects=False)
        body = response.json()
        report[label] = {
            "ok": response.status_code == 200 and body.get("ok") is True,
            "commit": body.get("deploymentCommit") if re.fullmatch(r"[0-9a-f]{40}", str(body.get("deploymentCommit", ""))) else None,
            "cloudflareHttpProxy": bool(response.headers.get("cf-ray")),
            "durableIdempotency": body.get("durableIdempotency") is True,
        }
    except Exception as exc:
        report[label] = {"ok": False, "errorClass": type(exc).__name__}
with transaction() as connection:
    row = connection.execute(text(
        "SELECT deployment_commit, delivery_enabled, wechat_enabled, activated_at IS NOT NULL "
        "AS activated FROM zacks.runtime_control WHERE singleton = true"
    )).mappings().one()
    report["control"] = dict(row)
    report["venueCount"] = connection.execute(text("SELECT count(*) FROM zacks.venue_status")).scalar_one()
    report["unhealthyVenues"] = connection.execute(text(
        "SELECT count(*) FROM zacks.venue_status WHERE NOT healthy "
        "OR last_inspection_at IS NULL OR last_inspection_at < now() - interval '10 minutes'"
    )).scalar_one()
    report["workers"] = [dict(row) for row in connection.execute(text(
        "SELECT component, deployment_commit, healthy, "
        "EXTRACT(EPOCH FROM now() - updated_at)::integer AS age_seconds "
        "FROM zacks.runtime_heartbeats ORDER BY component"
    )).mappings()]
try:
    from wechat_airflow.host_core.health import business_report
    business = business_report(report["runtimeCommit"], require_delivery=False)
    report["businessHealthy"] = business.get("ok") is True
    report["failedBusinessChecks"] = business.get("failedChecks", [])
except Exception as exc:
    report["businessHealthy"] = False
    report["businessErrorClass"] = type(exc).__name__
print(json.dumps(report, sort_keys=True))
"""


def health_summary(status: int, body: object) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"ok": False, "reason": "invalid_json_object"}
    commit = body.get("deploymentCommit")
    return {
        "ok": status == 200 and body.get("ok") is True,
        "commit": commit if isinstance(commit, str) and SHA.fullmatch(commit) else None,
        "durableIdempotency": body.get("durableIdempotency") is True,
        "appiumReady": body.get("appium_ready") is True,
        "deviceReady": body.get("device_ready") is True,
    }


def host_inventory(target_commit: str) -> dict[str, Any]:
    remote = airflow_remote()
    command = (
        f"cd {shlex.quote(remote['repository_path'])} && "
        f"DEPLOYMENT_COMMIT={target_commit} "
        f"AIRFLOW_IMAGE_NAME=wechat-on-airflow:host-{target_commit} "
        "docker compose exec -T zacks-api python -"
    )
    result = run([*ssh_command(remote), command], input_text=HOST_PROBE, check=False)
    if result.returncode:
        # SSH stderr can contain hostnames, database URLs, or Variable values.
        return {"ok": False, "reason": "host_inventory_failed", "exitCode": result.returncode}
    for line in reversed(result.stdout.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("externalTestSends") == 0:
            return value
    return {"ok": False, "reason": "host_inventory_result_missing"}


def read_channel_health(transport: Any, port: int) -> dict[str, Any]:
    channel = transport.open_channel(
        "direct-tcpip", ("127.0.0.1", port), ("127.0.0.1", 0), timeout=15
    )
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=25)
    channel.settimeout(25)
    connection.sock = channel
    try:
        connection.request("GET", "/readyz" if port == 7001 else "/healthz")
        response = connection.getresponse()
        data = response.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            return {"ok": False, "reason": "oversized_response"}
        return health_summary(response.status, json.loads(data))
    finally:
        connection.close()
        channel.close()


def tunnel_inventory(hostname: str) -> dict[str, Any]:
    import paramiko

    from wechat_airflow.clients.android_device import PinnedSHA256HostKeyPolicy

    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?", hostname):
        raise OpsError("invalid public SSH hostname")
    required = ("PI_DEVICE_SSH_USER", "PI_DEVICE_SSH_PASSWORD", "PI_DEVICE_SSH_HOST_KEY_SHA256")
    if any(not os.environ.get(name) for name in required):
        return {"ok": False, "reason": "protected_pi_credentials_missing"}
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    proxy = None
    client = paramiko.SSHClient()
    report: dict[str, Any] = {"ok": False, "externalTestSends": 0}
    try:
        client.set_missing_host_key_policy(PinnedSHA256HostKeyPolicy(os.environ[required[2]]))
        proxy = paramiko.ProxyCommand(f"cloudflared access ssh --hostname {shlex.quote(hostname)}")
        client.connect(
            hostname,
            port=22,
            username=os.environ[required[0]],
            password=os.environ[required[1]],
            sock=proxy,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
            allow_agent=False,
            look_for_keys=False,
        )
        report["pinnedSshAuthenticated"] = True
        transport = client.get_transport()
        for name, port in (("sender", 7001), ("scraper", 8788)):
            try:
                report[name] = read_channel_health(transport, port)
            except Exception as exc:
                report[name] = {"ok": False, "errorClass": type(exc).__name__}
        report["ok"] = all(report[name].get("ok") for name in ("sender", "scraper"))
    except Exception as exc:
        report["errorClass"] = type(exc).__name__
    finally:
        client.close()
        if proxy is not None:
            proxy.close()
            try:
                proxy.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proxy.process.kill()
                proxy.process.wait(timeout=5)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-commit", required=True)
    args = parser.parse_args()
    if not SHA.fullmatch(args.target_commit):
        raise OpsError("target must be a full commit SHA")
    config = json.loads((REPO_ROOT / "config/device-network.json").read_text())
    report = {
        "mode": "read_only_preflight",
        "targetCommit": args.target_commit,
        "host": host_inventory(args.target_commit),
        "tunnel": tunnel_inventory(config["public_ssh_hostname"]),
        "configurationChanged": False,
        "externalTestSends": 0,
        "retirementAuthorized": False,
    }
    host = report["host"]
    ok = (
        report["tunnel"].get("ok") is True
        and host.get("api", {}).get("ok") is True
        and host.get("unhealthyVenues") == 0
        and host.get("businessHealthy") is True
        and report["tunnel"].get("sender", {}).get("commit") == host.get("sender", {}).get("commit")
        and host.get("api", {}).get("commit") == host.get("runtimeCommit")
    )
    report["ok"] = ok
    emit(report, "json")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"device-network-preflight: {exc}")
        raise SystemExit(1) from None
