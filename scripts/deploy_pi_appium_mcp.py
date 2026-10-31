"""GitHub-only Pi MCP release and Cloudflare machine-auth provisioning."""

from __future__ import annotations

import base64
import copy
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

HOSTNAME = "appium-mcp.zacks.vision"
PREVIOUS_HOSTNAME = "appium-mcp.claude89757.cc"
RESOURCE_NAME = "Pi Appium MCP"
ZONE_ID = "8b0b6ef700b6a826539e597a3e1ec2b2"
PREVIOUS_ZONE_ID = "741a41032993004661579d76e63668bf"
SOURCE = Path(__file__).resolve().parents[1] / "pi_host/appium_mcp"
OWNER_USER_ID = "4f82fb39465f8effc6486128697946f3"
CLOUDFLARE_IDP_ID = "5fbaa521-5f28-43bc-a656-009215fa1b95"
TEAM_DOMAIN = "zacks-vision-ops.cloudflareaccess.com"
OWNER_POLICY_NAME = "Owner cloud agent OAuth"
BIC_RULE = {
    "ref": "pi_mcp_native_clients_bic_only",
    "description": RESOURCE_NAME + " native clients: BIC only",
    "expression": f'(http.host eq "{HOSTNAME}")',
    "action": "skip",
    "action_parameters": {"products": ["bic"]},
    "logging": {"enabled": True},
    "enabled": True,
}
OAUTH_CONFIGURATION = {
    "enabled": True,
    "dynamic_client_registration": {
        "enabled": True,
        "allow_any_on_localhost": True,
        "allow_any_on_loopback": True,
        "allowed_uris": [
            "https://chatgpt.com/connector/oauth/*",
            "https://chatgpt.com/connector_platform_oauth_redirect",
            "cursor://anysphere.cursor-mcp/oauth/callback",
            "https://www.cursor.com/agents/mcp/oauth/callback",
            "https://www.cursor.com/bot/mcp/oauth/callback",
            "https://grok.com/connectors-oauth-exchange-code/",
        ],
    },
    "grant": {"access_token_lifetime": "15m", "session_duration": "168h"},
}


def owner_identity():
    # Resolve PII only inside the protected runner; never return it in reports.
    try:
        user = cf("GET", "/user")
    except urllib.error.HTTPError as exc:
        if exc.code not in (401, 403):
            raise
        user = {}
    if user.get("id") != OWNER_USER_ID:
        members = cf("GET", f"/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/members?per_page=50")
        matches = [
            item["user"]
            for item in members
            if item.get("status") == "accepted" and item.get("user", {}).get("id") == OWNER_USER_ID
        ]
        if len(members) >= 50 or len(matches) != 1:
            raise RuntimeError("owner_identity_unavailable")
        user = matches[0]
    email = user.get("email")
    if not isinstance(email, str) or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        raise RuntimeError("owner_identity_unavailable")
    return email


def owner_policy(email):
    return {
        "name": OWNER_POLICY_NAME,
        "decision": "allow",
        "precedence": 2,
        "include": [{"email": {"email": email}}],
        "exclude": [],
        "require": [{"login_method": {"id": CLOUDFLARE_IDP_ID}}],
    }


def validate_access_policies(policies, credentials):
    machine = [policy for policy in policies if policy.get("decision") == "non_identity"]
    if (
        len(machine) != 1
        or machine[0].get("include") != [{"service_token": {"token_id": credentials["token_id"]}}]
        or machine[0].get("exclude")
        or machine[0].get("require")
    ):
        raise RuntimeError("access_ownership_mismatch")
    others = [policy for policy in policies if policy is not machine[0]]
    if others and (
        len(others) != 1
        or any(others[0].get(key) != value for key, value in owner_policy(owner_identity()).items())
    ):
        raise RuntimeError("access_ownership_mismatch")


class RemoteOperationError(RuntimeError):
    def __init__(self, error_class, test_report=None, connector=None):
        super().__init__("pi_operation_failed")
        self.error_class = error_class
        self.test_report = test_report
        self.connector = connector


def safe_connector_report(value):
    if not isinstance(value, dict) or set(value) != {
        "ready",
        "active",
        "exitCode",
        "restarts",
        "events",
    }:
        return None
    if any(type(value[key]) is not bool for key in ("ready", "active")):
        return None
    if any(
        type(value[key]) is not int or not 0 <= value[key] <= 1000000
        for key in ("exitCode", "restarts")
    ):
        return None
    allowed = {
        "authentication",
        "configuration",
        "permission",
        "dns",
        "timeout",
        "network",
        "quic",
        "port_busy",
        "certificate",
    }
    if (
        not isinstance(value["events"], list)
        or len(value["events"]) > len(allowed)
        or any(type(event) is not str or event not in allowed for event in value["events"])
    ):
        return None
    return value


def safe_test_report(value):
    flags = {
        "parseError",
        "timedOut",
        "startupNotReady",
        "processExitedBeforeHandshake",
        "portBusy",
    }
    if not isinstance(value, dict) or set(value) != flags | {"total", "failed", "exitCode"}:
        return None
    if any(type(value[key]) is not bool for key in flags):
        return None
    if type(value["total"]) is not int or not 0 <= value["total"] <= 1000:
        return None
    if type(value["exitCode"]) is not int or not -128 <= value["exitCode"] <= 255:
        return None
    if not isinstance(value["failed"], list) or len(value["failed"]) > value["total"]:
        return None
    if any(type(index) is not int or not 1 <= index <= value["total"] for index in value["failed"]):
        return None
    return value


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
    if len(value) > 65536:
        raise RuntimeError("pi_operation_failed")
    if stdout.channel.recv_exit_status() != 0:
        error_class = None
        test_report = None
        connector = None
        try:
            report = json.loads(value)
            candidate = report.get("errorClass")
            if report.get("ok") is False and candidate in {
                "ValueError",
                "TypeError",
                "RuntimeError",
                "FileNotFoundError",
                "PermissionError",
                "TimeoutExpired",
                "OSError",
                "JSONDecodeError",
                "CandidateTestFailure",
                "ConnectorFailure",
            }:
                error_class = candidate
                if candidate == "CandidateTestFailure":
                    test_report = safe_test_report(report.get("candidateTests"))
                if candidate == "ConnectorFailure":
                    connector = safe_connector_report(report.get("connector"))
        except (ValueError, AttributeError, TypeError):
            pass
        raise RemoteOperationError(error_class, test_report, connector)
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
    remote(client, f"sudo -n python3 {shlex.quote(installer)} connector --commit {commit}")
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


def public_health(credentials, *, hostname=HOSTNAME):
    opener = urllib.request.build_opener(NoRedirect)
    for headers in (
        {},
        {"CF-Access-Client-Id": "invalid.access", "CF-Access-Client-Secret": "invalid"},
        {"Authorization": "Bearer invalid"},
    ):
        request = urllib.request.Request(f"https://{hostname}/mcp", headers=headers)
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
        "MCP_URL": f"https://{hostname}/mcp",
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
        "invalidBearerDenied": True,
        "authenticatedMcpVerified": True,
    }


def verify_public(credentials, hostname):
    for attempt in range(6):
        try:
            return public_health(credentials, hostname=hostname)
        except Exception:
            if attempt == 5:
                raise
            time.sleep(5)


class DomainMigrationFailure(RuntimeError):
    def __init__(self, rollback_verified, stage, cause):
        super().__init__("domain_migration_failed")
        self.rollback_verified = rollback_verified
        self.stage = stage
        self.cause_class = type(cause).__name__
        self.http_status = cause.code if isinstance(cause, urllib.error.HTTPError) else None


def owned_dns(zone, hostname, tunnel_id):
    records = cf("GET", f"/zones/{zone}/dns_records?name={hostname}")
    if len(records) > 1 or any(
        record.get("type") != "CNAME"
        or record.get("name") != hostname
        or record.get("content") != tunnel_id + ".cfargotunnel.com"
        or record.get("proxied") is not True
        or record.get("comment") != RESOURCE_NAME
        for record in records
    ):
        raise RuntimeError("dns_ownership_mismatch")
    return records


def dns_body(record):
    return {key: record[key] for key in ("type", "name", "content", "proxied", "ttl", "comment")}


def access_body(app, policies, hostnames):
    fields = (
        "name",
        "type",
        "app_launcher_visible",
        "service_auth_401_redirect",
        "session_duration",
        "allowed_idps",
        "auto_redirect_to_identity",
        "allow_authenticate_via_warp",
        "enable_binding_cookie",
        "http_only_cookie_attribute",
        "same_site_cookie_attribute",
        "options_preflight_bypass",
        "cors_headers",
        "skip_interstitial",
        "tags",
        "oauth_configuration",
        "allow_iframe",
        "custom_deny_message",
        "custom_deny_url",
        "custom_non_identity_deny_url",
        "custom_pages",
        "eager_redirect_cookie_setting",
        "logo_url",
        "mfa_config",
        "path_cookie_attribute",
        "read_service_tokens_from_header",
        "scim_config",
        "use_clientless_isolation_app_launcher_url",
    )
    body = {key: copy.deepcopy(app[key]) for key in fields if app.get(key) is not None}
    body.update(
        domain=hostnames[0],
        destinations=[{"type": "public", "uri": hostname} for hostname in hostnames],
        policies=[
            {
                key: copy.deepcopy(policy[key])
                for key in (
                    "id",
                    "name",
                    "decision",
                    "include",
                    "exclude",
                    "require",
                    "precedence",
                    "session_duration",
                    "purpose_justification_required",
                    "purpose_justification_prompt",
                    "approval_required",
                    "approval_groups",
                    "isolation_required",
                )
                if key in policy
            }
            for policy in policies
        ],
    )
    return body


def domain_snapshot(credentials):
    prefix = f"/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}"
    app_path = prefix + f"/access/apps/{credentials['app_id']}"
    app = cf("GET", app_path)
    policies = cf("GET", app_path + "/policies")
    allowed = {HOSTNAME, PREVIOUS_HOSTNAME}
    destinations = app.get("destinations", [])
    if (
        app.get("name") != RESOURCE_NAME
        or app.get("type") != "self_hosted"
        or app.get("domain") not in allowed
        or not app.get("aud")
        or app.get("service_auth_401_redirect") is not True
        or not destinations
        or len({item.get("uri") for item in destinations}) != len(destinations)
        or app.get("domain") not in {item.get("uri") for item in destinations}
        or any(
            item not in [{"type": "public", "uri": name} for name in allowed]
            for item in destinations
        )
    ):
        raise RuntimeError("access_ownership_mismatch")
    validate_access_policies(policies, credentials)
    apps = cf("GET", prefix + "/access/apps?per_page=100")
    if len(apps) >= 100 or any(
        other.get("id") != credentials["app_id"]
        and (
            other.get("domain") == HOSTNAME
            or any(item.get("uri") == HOSTNAME for item in (other.get("destinations") or []))
        )
        for other in apps
    ):
        raise RuntimeError("domain_access_conflict")
    config_path = prefix + f"/cfd_tunnel/{credentials['tunnel_id']}/configurations"
    config = cf("GET", config_path)["config"]
    ingress = config.get("ingress", [])
    rules = ingress[:-1]
    if (
        not rules
        or ingress[-1] != {"service": "http_status:404"}
        or len({rule.get("hostname") for rule in rules}) != len(rules)
        or any(
            rule.get("hostname") not in allowed
            or rule.get("service") != "http://127.0.0.1:3333"
            or rule.get("originRequest", {}).get("access", {}).get("required") is not True
            or rule.get("originRequest", {}).get("access", {}).get("audTag") != [app["aud"]]
            for rule in rules
        )
    ):
        raise RuntimeError("tunnel_ownership_mismatch")
    return {
        "app_path": app_path,
        "app": app,
        "policies": policies,
        "config_path": config_path,
        "config": config,
        "old_dns": owned_dns(PREVIOUS_ZONE_ID, PREVIOUS_HOSTNAME, credentials["tunnel_id"]),
        "new_dns": owned_dns(ZONE_ID, HOSTNAME, credentials["tunnel_id"]),
    }


def migrate_domain(credentials, *, apply):
    state = domain_snapshot(credentials)
    current = (
        HOSTNAME
        if state["new_dns"]
        and any(item.get("hostname") == HOSTNAME for item in state["config"]["ingress"])
        and {"type": "public", "uri": HOSTNAME} in state["app"]["destinations"]
        else PREVIOUS_HOSTNAME
    )
    verify_public(credentials, current)
    complete = (
        state["app"]["domain"] == HOSTNAME
        and state["app"]["destinations"] == [{"type": "public", "uri": HOSTNAME}]
        and len(state["config"]["ingress"]) == 2
        and state["config"]["ingress"][0]["hostname"] == HOSTNAME
        and not state["old_dns"]
        and bool(state["new_dns"])
    )
    if not apply or complete:
        return {
            "ok": True,
            "applied": False,
            "domainReady": complete,
            "publicUrl": f"https://{HOSTNAME}/mcp",
        }
    rule = copy.deepcopy(state["config"]["ingress"][0])
    stage = "protect_new_domain"
    try:
        cf(
            "PUT",
            state["app_path"],
            access_body(state["app"], state["policies"], [PREVIOUS_HOSTNAME, HOSTNAME]),
        )
        stage = "route_new_domain"
        dual_config = copy.deepcopy(state["config"])
        dual_config["ingress"] = [
            {**rule, "hostname": hostname} for hostname in (PREVIOUS_HOSTNAME, HOSTNAME)
        ] + [{"service": "http_status:404"}]
        cf("PUT", state["config_path"], {"config": dual_config})
        stage = "publish_new_dns"
        if not state["new_dns"]:
            cf(
                "POST",
                f"/zones/{ZONE_ID}/dns_records",
                {
                    "type": "CNAME",
                    "name": HOSTNAME,
                    "content": credentials["tunnel_id"] + ".cfargotunnel.com",
                    "proxied": True,
                    "ttl": 1,
                    "comment": RESOURCE_NAME,
                },
            )
        stage = "verify_new_domain"
        verify_public(credentials, HOSTNAME)
        stage = "retire_previous_domain"
        for record in state["old_dns"]:
            cf("DELETE", f"/zones/{PREVIOUS_ZONE_ID}/dns_records/{record['id']}")
        final_config = copy.deepcopy(dual_config)
        final_config["ingress"] = [{**rule, "hostname": HOSTNAME}, {"service": "http_status:404"}]
        cf("PUT", state["config_path"], {"config": final_config})
        cf("PUT", state["app_path"], access_body(state["app"], state["policies"], [HOSTNAME]))
        stage = "verify_final_domain"
        final = domain_snapshot(credentials)
        if (
            final["app"]["aud"] != state["app"]["aud"]
            or final["old_dns"]
            or not final["new_dns"]
            or final["app"]["domain"] != HOSTNAME
            or final["app"]["destinations"] != [{"type": "public", "uri": HOSTNAME}]
            or final["config"]["ingress"] != final_config["ingress"]
            or final["policies"][0]["id"] != state["policies"][0]["id"]
        ):
            raise RuntimeError("domain_cutover_incomplete")
        report = verify_public(credentials, HOSTNAME)
        return {
            "ok": True,
            "applied": True,
            "domainReady": True,
            "oldDomainRetired": True,
            "credentialsRotated": False,
            "publicUrl": f"https://{HOSTNAME}/mcp",
            **report,
        }
    except Exception as cause:
        restored = False
        try:
            if not state["new_dns"]:
                for record in owned_dns(ZONE_ID, HOSTNAME, credentials["tunnel_id"]):
                    cf("DELETE", f"/zones/{ZONE_ID}/dns_records/{record['id']}")
            cf(
                "PUT",
                state["app_path"],
                access_body(
                    state["app"],
                    state["policies"],
                    [item["uri"] for item in state["app"]["destinations"]],
                ),
            )
            cf("PUT", state["config_path"], {"config": state["config"]})
            if state["old_dns"] and not owned_dns(
                PREVIOUS_ZONE_ID, PREVIOUS_HOSTNAME, credentials["tunnel_id"]
            ):
                cf("POST", f"/zones/{PREVIOUS_ZONE_ID}/dns_records", dns_body(state["old_dns"][0]))
            verify_public(credentials, current)
            restored = True
        except Exception:
            pass
        raise DomainMigrationFailure(restored, stage, cause) from None


class OAuthConfigurationFailure(DomainMigrationFailure):
    def __init__(self, rollback_verified, stage, cause):
        super().__init__(rollback_verified, stage, cause)
        self.args = ("oauth_configuration_failed",)
        self.reason = (
            str(cause)
            if str(cause)
            in {
                "oauth_challenge_missing",
                "oauth_metadata_untrusted",
                "oauth_resource_mismatch",
                "oauth_issuer_mismatch",
                "oauth_protocol_incomplete",
                "oauth_metadata_invalid",
                "oauth_acceptance_failed",
                "access_ownership_mismatch",
                "bic_ownership_mismatch",
            }
            else None
        )


def bic_snapshot():
    try:
        ruleset = cf(
            "GET", f"/zones/{ZONE_ID}/rulesets/phases/http_request_firewall_custom/entrypoint"
        )
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        return {"ruleset": None, "rule": None}
    owned = [rule for rule in ruleset.get("rules", []) if rule.get("ref") == BIC_RULE["ref"]]
    if (
        ruleset.get("kind") != "zone"
        or ruleset.get("phase") != "http_request_firewall_custom"
        or len(owned) > 1
        or any(
            rule.get(key, {"enabled": True} if key == "logging" else None) != value
            for rule in owned
            for key, value in BIC_RULE.items()
        )
    ):
        raise RuntimeError("bic_ownership_mismatch")
    return {"ruleset": ruleset, "rule": owned[0] if owned else None}


def enable_bic_exception(state):
    if state["rule"]:
        return None
    if state["ruleset"]:
        updated = cf(
            "POST",
            f"/zones/{ZONE_ID}/rulesets/{state['ruleset']['id']}/rules",
            copy.deepcopy(BIC_RULE),
        )
    else:
        updated = cf(
            "POST",
            f"/zones/{ZONE_ID}/rulesets",
            {
                "name": RESOURCE_NAME + " API compatibility",
                "kind": "zone",
                "phase": "http_request_firewall_custom",
                "rules": [copy.deepcopy(BIC_RULE)],
            },
        )
    matches = [rule for rule in updated.get("rules", []) if rule.get("ref") == BIC_RULE["ref"]]
    if len(matches) != 1 or not matches[0].get("id") or not updated.get("id"):
        raise RuntimeError("bic_ownership_mismatch")
    return {
        "ruleset_id": updated["id"],
        "rule_id": matches[0]["id"],
        "created_ruleset": not state["ruleset"],
    }


def restore_bic_exception(marker):
    if not marker:
        return
    current = bic_snapshot()
    if (
        not current["rule"]
        or current["rule"]["id"] != marker["rule_id"]
        or current["ruleset"]["id"] != marker["ruleset_id"]
    ):
        raise RuntimeError("bic_ownership_mismatch")
    path = f"/zones/{ZONE_ID}/rulesets/{marker['ruleset_id']}"
    cf("DELETE", path + f"/rules/{marker['rule_id']}")
    if marker["created_ruleset"]:
        remaining = bic_snapshot()["ruleset"]
        if remaining and remaining["id"] == marker["ruleset_id"] and not remaining.get("rules"):
            cf("DELETE", path)


def oauth_restored(actual, expected):
    # Access materializes default DCR flags even when OAuth is disabled.
    if expected is None or expected.get("enabled") is False:
        return actual is None or actual.get("enabled") is False
    return actual == expected


def oauth_ready(app, policies):
    oauth = app.get("oauth_configuration") or {}
    return (
        oauth.get("enabled") is True
        and oauth.get("dynamic_client_registration")
        == OAUTH_CONFIGURATION["dynamic_client_registration"]
        and oauth.get("grant") == OAUTH_CONFIGURATION["grant"]
        and app.get("allowed_idps") == [CLOUDFLARE_IDP_ID]
        and app.get("auto_redirect_to_identity") is True
        and len(policies) == 2
    )


def oauth_discovery():
    opener = urllib.request.build_opener(NoRedirect)
    url = f"https://{HOSTNAME}/mcp"
    try:
        with opener.open(
            urllib.request.Request(url, headers={"Accept": "application/json"}), timeout=20
        ):
            raise RuntimeError("oauth_challenge_missing")
    except urllib.error.HTTPError as exc:
        challenge = exc.headers.get("WWW-Authenticate", "")
        if exc.code != 401:
            raise RuntimeError("oauth_challenge_missing") from None
    match = re.search(r'\bresource_metadata="([^"]+)"', challenge)
    if not challenge.lower().startswith("bearer "):
        raise RuntimeError("oauth_challenge_missing")

    def trusted_url(value, hosts):
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc not in hosts
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise RuntimeError("oauth_metadata_untrusted")
        return value

    def metadata(value, hosts):
        request = urllib.request.Request(
            trusted_url(value, hosts), headers={"Accept": "application/json"}
        )
        with opener.open(request, timeout=20) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise RuntimeError("oauth_metadata_invalid")
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise RuntimeError("oauth_metadata_invalid")
        return document

    # Access supports RFC 9728 and its documented RFC 8414 application bootstrap.
    resource = metadata(
        match[1] if match else f"https://{HOSTNAME}/.well-known/oauth-authorization-server",
        {HOSTNAME, TEAM_DOMAIN} if match else {HOSTNAME},
    )
    mode = "protected_resource"
    if not match or (
        resource.get("issuer") and not ({"resource", "authorization_servers"} & resource.keys())
    ):
        server = resource
        trusted_url(server.get("issuer", ""), {HOSTNAME, TEAM_DOMAIN})
        mode = "authorization_server"
    else:
        issuers = resource.get("authorization_servers", [])
        if resource.get("resource") not in (url, f"https://{HOSTNAME}") or len(issuers) != 1:
            raise RuntimeError("oauth_resource_mismatch")
        issuer = trusted_url(issuers[0], {HOSTNAME, TEAM_DOMAIN})
        parsed = urllib.parse.urlsplit(issuer)
        discovery = urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                "/.well-known/oauth-authorization-server" + parsed.path.rstrip("/"),
                "",
                "",
            )
        )
        server = (
            resource
            if resource.get("issuer") == issuer
            else metadata(discovery, {HOSTNAME, TEAM_DOMAIN})
        )
        if server.get("issuer") != issuer:
            raise RuntimeError("oauth_issuer_mismatch")
    for key in ("authorization_endpoint", "token_endpoint", "registration_endpoint"):
        trusted_url(server.get(key, ""), {HOSTNAME, TEAM_DOMAIN})
    if (
        "S256" not in server.get("code_challenge_methods_supported", [])
        or "code" not in server.get("response_types_supported", [])
        or not {"authorization_code", "refresh_token"}
        <= set(server.get("grant_types_supported", []))
    ):
        raise RuntimeError("oauth_protocol_incomplete")
    return {"oauthDiscoveryVerified": True, "pkceS256Advertised": True, "oauthDiscoveryMode": mode}


def verify_oauth_discovery():
    for attempt in range(6):
        try:
            return oauth_discovery()
        except Exception:
            if attempt == 5:
                raise
            time.sleep(5)


def configure_oauth(credentials, *, apply):
    state = domain_snapshot(credentials)
    bic = bic_snapshot()
    app, policies = state["app"], state["policies"]
    if (
        app["domain"] != HOSTNAME
        or app["destinations"] != [{"type": "public", "uri": HOSTNAME}]
        or state["old_dns"]
        or not state["new_dns"]
        or [rule.get("hostname") for rule in state["config"]["ingress"][:-1]] != [HOSTNAME]
    ):
        raise RuntimeError("oauth_requires_completed_domain_cutover")
    email = owner_identity()
    idps = cf("GET", f"/accounts/{os.environ['CLOUDFLARE_ACCOUNT_ID']}/access/identity_providers")
    if not any(
        item.get("id") == CLOUDFLARE_IDP_ID and item.get("type") == "cloudflare" for item in idps
    ):
        raise RuntimeError("owner_identity_provider_unavailable")
    verify_public(credentials, HOSTNAME)
    complete = oauth_ready(app, policies) and bool(bic["rule"])
    report = {
        "ok": True,
        "applied": False,
        "oauthReady": complete,
        "ownerIdentityVerified": True,
        "credentialsRotated": False,
        "publicUrl": f"https://{HOSTNAME}/mcp",
        "oauthLoginVerified": False,
        "bicExceptionReady": bool(bic["rule"]),
    }
    if complete:
        report.update(verify_oauth_discovery())
    if not apply or complete:
        return report
    stage = "enable_bic_exception"
    marker = None
    access_update_attempted = False
    try:
        marker = enable_bic_exception(bic)
        stage = "enable_owner_oauth"
        body = access_body(app, policies, [HOSTNAME])
        if len(policies) == 1:
            body["policies"].append(owner_policy(email))
        body.update(
            oauth_configuration=copy.deepcopy(OAUTH_CONFIGURATION),
            allowed_idps=[CLOUDFLARE_IDP_ID],
            auto_redirect_to_identity=True,
        )
        access_update_attempted = True
        cf("PUT", state["app_path"], body)
        stage = "verify_owner_oauth"
        final = domain_snapshot(credentials)
        if (
            not oauth_ready(final["app"], final["policies"])
            or final["app"]["aud"] != app["aud"]
            or final["config"] != state["config"]
            or final["new_dns"] != state["new_dns"]
            or not bic_snapshot()["rule"]
            or not {policy["id"] for policy in policies}
            <= {policy["id"] for policy in final["policies"]}
        ):
            raise RuntimeError("oauth_acceptance_failed")
        report.update(verify_oauth_discovery())
        report.update(verify_public(credentials, HOSTNAME))
        return {**report, "applied": True, "oauthReady": True, "bicExceptionReady": True}
    except Exception as cause:
        restored = False
        try:
            if access_update_attempted:
                body = access_body(app, policies, [HOSTNAME])
                body.setdefault("oauth_configuration", {"enabled": False})
                body.setdefault("allowed_idps", [])
                body.setdefault("auto_redirect_to_identity", False)
                cf("PUT", state["app_path"], body)
            restore_bic_exception(marker)
            final = domain_snapshot(credentials)
            if (
                final["app"]["aud"] != app["aud"]
                or not oauth_restored(
                    final["app"].get("oauth_configuration"), app.get("oauth_configuration")
                )
                or final["app"].get("allowed_idps", []) != app.get("allowed_idps", [])
                or final["app"].get("auto_redirect_to_identity", False)
                != app.get("auto_redirect_to_identity", False)
                or bool(bic_snapshot()["rule"]) != bool(bic["rule"])
                or {policy["id"] for policy in final["policies"]}
                != {policy["id"] for policy in policies}
            ):
                raise RuntimeError("oauth_restore_failed")
            verify_public(credentials, HOSTNAME)
            restored = True
        except Exception:
            pass
        raise OAuthConfigurationFailure(restored, stage, cause) from None


def runtime_starts(client):
    code = "import json,subprocess; units=['wechat-sender.service','zacks-agent.service','cloudflared-dsh.service','pi-appium-mcp.service','cloudflared-appium-mcp.service']; print(json.dumps({unit:subprocess.check_output(['systemctl','show',unit,'--property=ExecMainStartTimestampMonotonic','--value'],text=True).strip() for unit in units}))"
    return json.loads(remote(client, "python3 -c " + shlex.quote(code)))


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
        runtime_commit = os.environ.get("RUNTIME_COMMIT") or commit
        domain_operation = operation in {"domain_preflight", "domain_apply"}
        oauth_operation = operation in {"oauth_preflight", "oauth_apply"}
        edge_operation = domain_operation or oauth_operation
        if not re.fullmatch(r"[0-9a-f]{40}", commit) or operation not in {
            "preflight",
            "apply",
            "health",
            "withdraw",
            "rollback",
            "domain_preflight",
            "domain_apply",
            "oauth_preflight",
            "oauth_apply",
        }:
            raise ValueError("invalid_operation")
        if not re.fullmatch(r"[0-9a-f]{40}", runtime_commit) or (
            edge_operation and not os.environ.get("RUNTIME_COMMIT")
        ):
            raise ValueError("exact_runtime_commit_required")
        if os.environ.get("RUNTIME_COMMIT") and not (edge_operation or operation == "health"):
            raise ValueError("runtime_override_requires_readonly_or_edge_operation")
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
        host_operation = "health" if edge_operation else operation
        command = f"sudo -n python3 {shlex.quote(installer)} {host_operation} --commit {runtime_commit} --staging {shlex.quote(staging)}"
        phase = "pi_" + operation
        report = json.loads(remote(client, command))
        if not report.get("ok"):
            raise RuntimeError("pi_verification_failed")
        if edge_operation:
            phase = "cloudflare_oauth" if oauth_operation else "cloudflare_domain"
            if report.get("activePhoneSessions") != 0:
                raise RuntimeError("edge_change_requires_idle_control")
            starts = runtime_starts(client)
            configure = configure_oauth if oauth_operation else migrate_domain
            report.update(configure(read_credentials(client), apply=operation.endswith("_apply")))
            report.update(
                runtimeCommit=runtime_commit,
                controlPlaneCommit=commit,
                hostRuntimeUnchanged=starts == runtime_starts(client),
            )
            if not report["hostRuntimeUnchanged"]:
                raise RuntimeError("runtime_changed_during_edge_operation")
        elif operation == "apply":
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
            credentials = read_credentials(client)
            report.update(public_health(credentials))
            oauth_report = configure_oauth(credentials, apply=False)
            if not oauth_report["oauthReady"]:
                raise RuntimeError("oauth_not_ready")
            report.update(oauth_report)
            report.update(
                runtimeCommit=runtime_commit,
                controlPlaneCommit=commit,
                publicUrl=f"https://{HOSTNAME}/mcp",
            )
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
                    "remoteErrorClass": exc.error_class
                    if isinstance(exc, RemoteOperationError)
                    else None,
                    "candidateTests": exc.test_report
                    if isinstance(exc, RemoteOperationError)
                    else None,
                    "httpStatus": exc.code if isinstance(exc, urllib.error.HTTPError) else None,
                    "rollbackVerified": rollback_verified,
                    "domainRollbackVerified": exc.rollback_verified
                    if type(exc) is DomainMigrationFailure
                    else None,
                    "domainStage": exc.stage if type(exc) is DomainMigrationFailure else None,
                    "domainCauseClass": exc.cause_class
                    if type(exc) is DomainMigrationFailure
                    else None,
                    "domainHttpStatus": exc.http_status
                    if type(exc) is DomainMigrationFailure
                    else None,
                    "oauthRollbackVerified": exc.rollback_verified
                    if isinstance(exc, OAuthConfigurationFailure)
                    else None,
                    "oauthStage": exc.stage if isinstance(exc, OAuthConfigurationFailure) else None,
                    "oauthCauseClass": exc.cause_class
                    if isinstance(exc, OAuthConfigurationFailure)
                    else None,
                    "oauthFailureReason": exc.reason
                    if isinstance(exc, OAuthConfigurationFailure)
                    else None,
                    "oauthHttpStatus": exc.http_status
                    if isinstance(exc, OAuthConfigurationFailure)
                    else None,
                    "connector": exc.connector if isinstance(exc, RemoteOperationError) else None,
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
