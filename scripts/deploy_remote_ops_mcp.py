"""GitHub-protected per-host operations MCP and owner-managed access groups."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shlex
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import deploy_pi_appium_mcp as phone
import paramiko

TARGETS = {
    "pi": ("pi-mcp.zacks.vision", "Zacks Pi administrators"),
    "vps": ("vps-mcp.zacks.vision", "Zacks VPS administrators"),
    "phone": ("appium-mcp.zacks.vision", "Zacks phone operators"),
}


def group(name, apply):
    prefix = f"/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/access/groups"
    groups = phone.cf("GET", prefix + "?per_page=100")
    matches = [item for item in groups if item.get("name") == name]
    if len(groups) >= 100 or len(matches) > 1:
        raise RuntimeError("group_ownership_ambiguous")
    if matches:
        return matches[0]["id"]
    if not apply:
        return None
    # Membership is owner-managed after creation. Never PUT a group during deploy.
    return phone.cf(
        "POST",
        prefix,
        {
            "name": name,
            "include": [{"email": {"email": phone.owner_identity()}}],
            "exclude": [],
            "require": [],
        },
    )["id"]


def group_policy(group_id, name, precedence=2):
    return {
        "name": name,
        "decision": "allow",
        "precedence": precedence,
        "include": [{"group": {"id": group_id}}],
        "exclude": [],
        "require": [{"login_method": {"id": phone.CLOUDFLARE_IDP_ID}}],
    }


def connect(target):
    client = paramiko.SSHClient()
    if target in {"pi", "phone"}:
        client.set_missing_host_key_policy(phone.PinnedHostKey())
        client.connect(
            os.environ["PI_DEVICE_SSH_HOST"],
            port=int(os.environ["PI_DEVICE_SSH_PORT"]),
            username=os.environ["PI_DEVICE_SSH_USER"],
            password=os.environ["PI_DEVICE_SSH_PASSWORD"],
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            auth_timeout=15,
        )
    else:
        for line in os.environ["AIRFLOW_SSH_KNOWN_HOSTS"].splitlines():
            if not line.strip() or line.startswith("#"):
                continue
            entry = paramiko.hostkeys.HostKeyEntry.from_line(line)
            if entry:
                for hostname in entry.hostnames:
                    client.get_host_keys().add(hostname, entry.key.get_name(), entry.key)
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        key = None
        for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                key = cls.from_private_key(io.StringIO(os.environ["AIRFLOW_SSH_PRIVATE_KEY"]))
                break
            except paramiko.SSHException:
                pass
        if key is None:
            raise RuntimeError("ssh_key_invalid")
        client.connect(
            os.environ["AIRFLOW_SSH_HOST"],
            port=int(os.environ["AIRFLOW_SSH_PORT"]),
            username=os.environ["AIRFLOW_SSH_USER"],
            pkey=key,
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            auth_timeout=15,
        )
    return client


def credential_read(client):
    return json.loads(
        phone.remote(
            client,
            "sudo -n python3 -c "
            + shlex.quote(
                "from pathlib import Path; p=Path('/etc/zacks-ops-mcp/cloudflare.json'); print(p.read_text() if p.exists() else '{}')"
            ),
        )
    )


def save(client, installer, commit, value):
    phone.remote(
        client, f"sudo -n python3 {installer} credentials --commit {commit}", json.dumps(value)
    )


def provision(client, installer, commit, target):
    hostname, group_name = TARGETS[target]
    prefix = f"/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
    credentials = credential_read(client)
    group_id = group(group_name, True)
    name = f"Zacks {target} operations MCP"
    if not credentials:
        apps = phone.cf("GET", prefix + "/access/apps?per_page=100")
        tunnels = phone.cf("GET", prefix + "/cfd_tunnel?is_deleted=false&per_page=100")
        if (
            len(apps) >= 100
            or len(tunnels) >= 100
            or any(a.get("domain") == hostname for a in apps)
            or any(t.get("name") == name for t in tunnels)
        ):
            raise RuntimeError("unowned_resource_exists")
        if phone.cf("GET", f"/zones/{phone.ZONE_ID}/dns_records?name={hostname}"):
            raise RuntimeError("unowned_dns_exists")
        credentials = {"hostname": hostname, "group_id": group_id}
        save(client, installer, commit, credentials)
    if credentials.get("hostname") != hostname or credentials.get("group_id") != group_id:
        raise RuntimeError("resource_identity_mismatch")
    if "token_id" not in credentials:
        token = phone.cf(
            "POST",
            prefix + "/access/service_tokens",
            {"name": name + " health", "duration": "2160h"},
        )
        credentials.update(
            token_id=token["id"],
            access_client_id=token["client_id"],
            access_client_secret=token["client_secret"],
        )
        save(client, installer, commit, credentials)
    machine = {
        "name": "Dedicated health only",
        "decision": "non_identity",
        "precedence": 1,
        "include": [{"service_token": {"token_id": credentials["token_id"]}}],
        "require": [],
        "exclude": [],
    }
    desired = {
        "name": name,
        "type": "self_hosted",
        "domain": hostname,
        "destinations": [{"type": "public", "uri": hostname}],
        "app_launcher_visible": True,
        "service_auth_401_redirect": True,
        "session_duration": "1h",
        "allowed_idps": [phone.CLOUDFLARE_IDP_ID],
        "auto_redirect_to_identity": True,
        "oauth_configuration": copy.deepcopy(phone.OAUTH_CONFIGURATION),
        "policies": [machine, group_policy(group_id, group_name)],
    }
    if "app_id" not in credentials:
        app = phone.cf("POST", prefix + "/access/apps", desired)
        credentials.update(app_id=app["id"], audience=app["aud"])
        save(client, installer, commit, credentials)
    else:
        app = phone.cf("GET", prefix + f"/access/apps/{credentials['app_id']}")
        policies = phone.cf("GET", prefix + f"/access/apps/{credentials['app_id']}/policies")
        if (
            any(app.get(k) != v for k, v in desired.items() if k not in {"policies"})
            or len(policies) != 2
        ):
            raise RuntimeError("access_configuration_drift")
        for expected in desired["policies"]:
            if not any(all(p.get(k) == v for k, v in expected.items()) for p in policies):
                raise RuntimeError("access_policy_drift")
    if "tunnel_id" not in credentials:
        tunnel = phone.cf(
            "POST", prefix + "/cfd_tunnel", {"name": name, "config_src": "cloudflare"}
        )
        credentials["tunnel_id"] = tunnel["id"]
        save(client, installer, commit, credentials)
    if "tunnel_token" not in credentials:
        credentials["tunnel_token"] = phone.cf(
            "GET", prefix + f"/cfd_tunnel/{credentials['tunnel_id']}/token"
        )
        save(client, installer, commit, credentials)
    phone.cf(
        "PUT",
        prefix + f"/cfd_tunnel/{credentials['tunnel_id']}/configurations",
        {
            "config": {
                "ingress": [
                    {
                        "hostname": hostname,
                        "service": "http://127.0.0.1:3340",
                        "originRequest": {
                            "access": {
                                "required": True,
                                "teamName": phone.TEAM_DOMAIN.removesuffix(".cloudflareaccess.com"),
                                "audTag": [credentials["audience"]],
                            }
                        },
                    },
                    {"service": "http_status:404"},
                ]
            }
        },
    )
    return credentials


def publish(credentials):
    prefix = f"/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
    for _ in range(30):
        tunnel = phone.cf("GET", prefix + f"/cfd_tunnel/{credentials['tunnel_id']}")
        if tunnel.get("status") == "healthy":
            break
        time.sleep(2)
    else:
        raise RuntimeError("tunnel_not_ready")
    hostname = credentials["hostname"]
    records = phone.cf("GET", f"/zones/{phone.ZONE_ID}/dns_records?name={hostname}")
    content = credentials["tunnel_id"] + ".cfargotunnel.com"
    if records:
        if (
            len(records) != 1
            or records[0].get("content") != content
            or not records[0].get("proxied")
        ):
            raise RuntimeError("dns_identity_mismatch")
    else:
        phone.cf(
            "POST",
            f"/zones/{phone.ZONE_ID}/dns_records",
            {
                "type": "CNAME",
                "name": hostname,
                "content": content,
                "proxied": True,
                "ttl": 1,
                "comment": "Zacks operations MCP",
            },
        )


def public_health(credentials, commit):
    url = f"https://{credentials['hostname']}/mcp"
    opener = urllib.request.build_opener(phone.NoRedirect())
    for headers in ({}, {"Authorization": "Bearer invalid"}):
        try:
            opener.open(urllib.request.Request(url, headers=headers), timeout=20)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise RuntimeError("oauth_challenge_missing") from None
        else:
            raise RuntimeError("anonymous_access_allowed")
    headers = {
        "CF-Access-Client-Id": credentials["access_client_id"],
        "CF-Access-Client-Secret": credentials["access_client_secret"],
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    def call(method, params):
        payload = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode()
        with opener.open(
            urllib.request.Request(url, data=payload, headers=headers), timeout=30
        ) as response:
            value = json.load(response)
        if "error" in value:
            raise RuntimeError("mcp_probe_failed")
        return value["result"]

    call(
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "protected-health", "version": "1"},
        },
    )
    tools = call("tools/list", {})["tools"]
    if {tool["name"] for tool in tools} != {
        "ops_status",
        "ops_request",
        "ops_result",
        "ops_github",
    }:
        raise RuntimeError("tools_mismatch")
    status = json.loads(
        call("tools/call", {"name": "ops_status", "arguments": {}})["content"][0]["text"]
    )
    if status.get("commit") != commit or not status.get("approvalRequired"):
        raise RuntimeError("runtime_identity_mismatch")
    phone.HOSTNAME = credentials["hostname"]
    discovery = phone.verify_oauth_discovery()
    return {
        **discovery,
        "ok": True,
        "tools": len(tools),
        "anonymousDenied": True,
        "invalidBearerDenied": True,
        "authenticatedMcpVerified": True,
        "administratorCommandsExecuted": 0,
    }


def phone_access(client, apply):
    credentials = phone.read_credentials(client)
    state = phone.domain_snapshot(credentials)
    group_id = group(TARGETS["phone"][1], apply)
    expected = group_policy(group_id, TARGETS["phone"][1], 3)
    ready = (
        any(all(p.get(k) == v for k, v in expected.items()) for p in state["policies"])
        if group_id
        else False
    )
    if apply and not ready:
        body = phone.access_body(state["app"], state["policies"], [phone.HOSTNAME])
        body["policies"].append(expected)
        try:
            phone.cf("PUT", state["app_path"], body)
            phone.domain_snapshot(credentials)
            phone.verify_public(credentials, phone.HOSTNAME)
        except Exception:
            phone.cf(
                "PUT",
                state["app_path"],
                phone.access_body(state["app"], state["policies"], [phone.HOSTNAME]),
            )
            raise
        ready = True
    report = phone.verify_public(credentials, phone.HOSTNAME)
    return {**report, "ok": True, "collaboratorsReady": ready, "membershipOverwritten": False}


def main():
    target, operation, commit = (
        os.environ[key] for key in ("OPS_TARGET", "OPERATION", "TARGET_COMMIT")
    )
    if (
        target not in TARGETS
        or operation not in {"preflight", "apply", "health", "withdraw"}
        or not re.fullmatch("[a-f0-9]{40}", commit)
    ):
        raise ValueError("invalid_operation")
    client = connect(target)
    staging = "/tmp/remote-ops-" + uuid.uuid4().hex
    try:
        if target == "phone":
            if operation == "withdraw":
                raise ValueError("phone_withdraw_not_supported")
            report = phone_access(client, operation == "apply")
            if operation == "health" and not report["collaboratorsReady"]:
                raise RuntimeError("collaborator_policy_missing")
            print(json.dumps(report))
            return
        phone.remote(client, "mkdir -m 700 " + staging)
        installer = staging + "/install.py"
        with client.open_sftp() as sftp:
            sftp.put("pi_host/remote_ops/install.py", installer)
        prefix = f"sudo -n python3 {installer}"
        preflight = json.loads(phone.remote(client, f"{prefix} preflight --commit {commit}"))
        if operation == "preflight":
            group(TARGETS[target][1], False)
            print(json.dumps({**preflight, "target": target, "applied": False}))
            return
        if operation == "withdraw":
            print(phone.remote(client, f"{prefix} withdraw --commit {commit}"))
            return
        if operation == "apply":
            credentials = provision(client, installer, commit, target)
            # Reuse the already tested exact-host BIC-only exception implementation.
            phone.HOSTNAME = TARGETS[target][0]
            phone.BIC_RULE = {
                **phone.BIC_RULE,
                "ref": f"zacks_ops_{target}_bic_only",
                "description": f"Zacks {target} MCP native clients: BIC only",
                "expression": f'(http.host eq "{phone.HOSTNAME}")',
            }
            phone.enable_bic_exception(phone.bic_snapshot())
            archive = Path("/tmp/remote-ops-release/source.tar.gz")
            with client.open_sftp() as sftp:
                sftp.put(str(archive), staging + "/source.tar.gz")
                name = f"node-{preflight['architecture']}.tar.xz"
                sftp.put("/tmp/remote-ops-release/" + name, staging + "/" + name)
            payload = {
                "credentials": credentials,
                "runtime": {
                    "target": target,
                    "origin": "https://" + TARGETS[target][0],
                    "issuer": "https://" + phone.TEAM_DOMAIN,
                    "audience": credentials["audience"],
                },
            }
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            phone.remote(
                client,
                f"{prefix} apply --commit {commit} --staging {staging} --source-sha256 {digest}",
                json.dumps(payload),
            )
            publish(credentials)
        else:
            credentials = credential_read(client)
            phone.remote(client, f"{prefix} health --commit {commit}")
        for attempt in range(6):
            try:
                report = public_health(credentials, commit)
                break
            except Exception:
                if attempt == 5:
                    if operation == "apply":
                        phone.remote(client, f"{prefix} withdraw --commit {commit}")
                    raise
                time.sleep(5)
        print(
            json.dumps(
                {
                    **report,
                    "target": target,
                    "runtimeCommit": commit,
                    "publicUrl": "https://" + TARGETS[target][0] + "/mcp",
                }
            )
        )
    finally:
        try:
            phone.remote(client, "rm -rf -- " + staging, timeout=30)
        finally:
            client.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "errorClass": type(exc).__name__}))
        raise SystemExit(1) from None
