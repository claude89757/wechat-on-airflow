"""GitHub-only Pi MCP release and Cloudflare machine-auth provisioning."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import shlex
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import paramiko

HOSTNAME = "appium-mcp.claude89757.cc"
RESOURCE_NAME = "Pi Appium MCP"
ZONE_ID = "741a41032993004661579d76e63668bf"
SOURCE = Path(__file__).resolve().parents[1] / "pi_host/appium_mcp"


def cf(method, path, body=None):
    request = urllib.request.Request(
        "https://api.cloudflare.com/client/v4" + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": "Bearer " + os.environ["CLOUDFLARE_API_TOKEN"],
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if not data.get("success"):
        raise RuntimeError("cloudflare_operation_failed")
    return data["result"]


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        actual = "SHA256:" + base64.b64encode(
            hashlib.sha256(key.asbytes()).digest()
        ).decode().rstrip("=")
        expected = os.environ["PI_DEVICE_SSH_HOST_KEY_SHA256"].strip().rstrip("=")
        if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", expected) or not hmac.compare_digest(
            actual, expected
        ):
            raise paramiko.SSHException("host_key_mismatch")


def remote(client, command, payload="", timeout=900):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    stdin.write(payload)
    stdin.flush()
    stdin.channel.shutdown_write()
    value = stdout.read(65537)
    # Never forward raw remote stderr or exception messages.
    stderr.read(65537)
    if len(value) > 65536 or stdout.channel.recv_exit_status() != 0:
        raise RuntimeError("pi_operation_failed")
    return value.decode()


def read_credentials(client):
    credential_command = "sudo -n python3 -c " + shlex.quote(
        "from pathlib import Path; p=Path('/etc/pi-appium-mcp/cloudflare.json'); print(p.read_text() if p.exists() else '{}')"
    )
    return json.loads(remote(client, credential_command))


def provision(client, installer, commit):
    prefix = f"/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
    existing = read_credentials(client)
    if existing:
        credentials = existing
    else:
        apps = cf("GET", prefix + "/access/apps?per_page=100")
        tunnels = cf("GET", prefix + "/cfd_tunnel?is_deleted=false&per_page=100")
        if any(app.get("domain") == HOSTNAME for app in apps) or any(
            t.get("name") == RESOURCE_NAME for t in tunnels
        ):
            raise RuntimeError("existing_cloudflare_ownership_requires_review")
        if cf("GET", f"/zones/{ZONE_ID}/dns_records?name={HOSTNAME}"):
            raise RuntimeError("existing_dns_requires_review")
        app = cf(
            "POST",
            prefix + "/access/apps",
            {
                "name": RESOURCE_NAME,
                "type": "self_hosted",
                "domain": HOSTNAME,
                "destinations": [{"type": "public", "uri": HOSTNAME}],
                "app_launcher_visible": False,
                "service_auth_401_redirect": True,
                "session_duration": "1h",
            },
        )
        token = cf(
            "POST",
            prefix + "/access/service_tokens",
            {"name": RESOURCE_NAME + " agent", "duration": "2160h"},
        )
        cf(
            "POST",
            prefix + f"/access/apps/{app['id']}/policies",
            {
                "name": "Dedicated cloud agent only",
                "decision": "non_identity",
                "precedence": 1,
                "include": [{"service_token": {"token_id": token["id"]}}],
                "exclude": [],
                "require": [],
            },
        )
        tunnel = cf(
            "POST", prefix + "/cfd_tunnel", {"name": RESOURCE_NAME, "config_src": "cloudflare"}
        )
        organization = cf("GET", prefix + "/access/organizations")
        team = organization["auth_domain"].removesuffix(".cloudflareaccess.com")
        cf(
            "PUT",
            prefix + f"/cfd_tunnel/{tunnel['id']}/configurations",
            {
                "config": {
                    "ingress": [
                        {
                            "hostname": HOSTNAME,
                            "service": "http://127.0.0.1:3333",
                            "originRequest": {
                                "access": {
                                    "required": True,
                                    "teamName": team,
                                    "audTag": [app["aud"]],
                                }
                            },
                        },
                        {"service": "http_status:404"},
                    ]
                }
            },
        )
        tunnel_token = cf("GET", prefix + f"/cfd_tunnel/{tunnel['id']}/token")
        credentials = {
            "tunnel_token": tunnel_token,
            "access_client_id": token["client_id"],
            "access_client_secret": token["client_secret"],
            "tunnel_id": tunnel["id"],
            "app_id": app["id"],
            "token_id": token["id"],
        }
        remote(
            client,
            f"sudo -n python3 {shlex.quote(installer)} credentials --commit {commit}",
            json.dumps(credentials),
        )
    remote(client, "sudo -n systemctl enable --now cloudflared-appium-mcp.service")
    for _ in range(30):
        tunnel = cf("GET", prefix + f"/cfd_tunnel/{credentials['tunnel_id']}")
        if tunnel.get("status") == "healthy":
            break
        time.sleep(2)
    else:
        raise RuntimeError("connector_not_healthy")
    records = cf("GET", f"/zones/{ZONE_ID}/dns_records?name={HOSTNAME}")
    target = credentials["tunnel_id"] + ".cfargotunnel.com"
    if records:
        if (
            len(records) != 1
            or records[0].get("content") != target
            or not records[0].get("proxied")
        ):
            raise RuntimeError("dns_ownership_mismatch")
    else:
        cf(
            "POST",
            f"/zones/{ZONE_ID}/dns_records",
            {
                "type": "CNAME",
                "name": HOSTNAME,
                "content": target,
                "proxied": True,
                "ttl": 1,
                "comment": RESOURCE_NAME,
            },
        )
    return credentials


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def public_health(credentials):
    opener = urllib.request.build_opener(NoRedirect)
    for headers in (
        {},
        {"CF-Access-Client-Id": "invalid.access", "CF-Access-Client-Secret": "invalid"},
    ):
        request = urllib.request.Request(f"https://{HOSTNAME}/mcp", headers=headers)
        try:
            with opener.open(request, timeout=20) as response:
                status = response.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        if status not in (401, 403):
            raise RuntimeError("anonymous_access_not_denied")
    environment = {
        **{
            key: os.environ[key]
            for key in ("PATH", "HOME", "LANG", "LC_ALL", "NODE_EXTRA_CA_CERTS")
            if key in os.environ
        },
        "MCP_URL": f"https://{HOSTNAME}/mcp",
        "CF_ACCESS_CLIENT_ID": credentials["access_client_id"],
        "CF_ACCESS_CLIENT_SECRET": credentials["access_client_secret"],
    }
    result = subprocess.run(
        ["node", str(SOURCE / "smoke.mjs")], env=environment, capture_output=True, timeout=30
    )
    if result.returncode or not json.loads(result.stdout).get("ok"):
        raise RuntimeError("authenticated_public_probe_failed")
    return {
        "anonymousDenied": True,
        "invalidCredentialDenied": True,
        "authenticatedMcpVerified": True,
    }


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey())
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    staging = ""
    phase = "validate"
    application_applied = False
    try:
        commit = os.environ["TARGET_COMMIT"]
        operation = os.environ["OPERATION"]
        if not re.fullmatch(r"[0-9a-f]{40}", commit) or operation not in {
            "preflight",
            "apply",
            "health",
            "withdraw",
            "rollback",
        }:
            raise ValueError("invalid_operation")
        if operation in {"preflight", "apply"}:
            phase = "cloudflare_permissions"
            prefix = f"/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
            for path in (
                "/access/apps",
                "/access/service_tokens",
                "/access/organizations",
                "/cfd_tunnel",
            ):
                cf("GET", prefix + path)
            cf("GET", f"/zones/{ZONE_ID}/dns_records?name={HOSTNAME}")
        phase = "pinned_ssh"
        client.connect(
            os.environ["PI_DEVICE_SSH_HOST"],
            port=int(os.environ["PI_DEVICE_SSH_PORT"]),
            username=os.environ["PI_DEVICE_SSH_USER"],
            password=os.environ["PI_DEVICE_SSH_PASSWORD"],
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
            disabled_algorithms={"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
        )
        phase = "upload"
        staging = "/tmp/pi-mcp-release-" + uuid.uuid4().hex
        remote(client, "mkdir -m 700 " + shlex.quote(staging))
        with client.open_sftp() as sftp:
            installer = staging + "/install.py"
            sftp.put(str(SOURCE / "install.py"), installer)
            if operation in {"preflight", "apply"}:
                for name in ("source.tar.gz", "cache.tar.gz", "node.tar.xz"):
                    sftp.put(str(Path("/tmp/pi-mcp-release") / name), staging + "/" + name)
        command = f"sudo -n python3 {shlex.quote(installer)} {operation} --commit {commit} --staging {shlex.quote(staging)}"
        phase = "pi_" + operation
        report = json.loads(remote(client, command))
        if not report.get("ok"):
            raise RuntimeError("pi_verification_failed")
        if operation == "apply":
            application_applied = True
            phase = "cloudflare_provision"
            credentials = provision(client, installer, commit)
            phase = "public_auth_acceptance"
            for attempt in range(6):
                try:
                    report.update(public_health(credentials))
                    break
                except Exception:
                    if attempt == 5:
                        raise
                    time.sleep(5)
        elif operation == "health":
            phase = "public_auth_acceptance"
            report.update(public_health(read_credentials(client)))
        print(json.dumps(report, sort_keys=True))
        return 0
    except Exception as exc:
        rollback_verified = False
        if application_applied:
            try:
                rollback = json.loads(
                    remote(
                        client,
                        f"sudo -n python3 {shlex.quote(installer)} rollback --commit {commit}",
                    )
                )
                rollback_verified = rollback.get("ok") is True
            except Exception:
                pass
        print(
            json.dumps(
                {
                    "ok": False,
                    "phase": phase,
                    "errorClass": type(exc).__name__,
                    "httpStatus": exc.code if isinstance(exc, urllib.error.HTTPError) else None,
                    "rollbackVerified": rollback_verified,
                    "externalTestSends": 0,
                }
            )
        )
        return 1
    finally:
        if staging:
            try:
                remote(client, "rm -rf -- " + shlex.quote(staging), timeout=30)
            except Exception:
                pass
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
