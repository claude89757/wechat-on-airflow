from __future__ import annotations

import copy
import importlib.util
import io
import json
import urllib.error
from email.message import Message
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("pi_domain", ROOT / "scripts/deploy_pi_appium_mcp.py")
assert SPEC and SPEC.loader
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


@pytest.fixture
def cloudflare(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    monkeypatch.setattr(DEPLOY.time, "sleep", lambda _: None)
    credentials = {
        "app_id": "test-app",
        "tunnel_id": "test-tunnel",
        "token_id": "test-token",
        "access_client_secret": "fake-private-secret",
    }
    policy = {
        "id": "policy-test",
        "name": "Dedicated",
        "precedence": 1,
        "decision": "non_identity",
        "include": [{"service_token": {"token_id": "test-token"}}],
        "exclude": [],
        "require": [],
    }
    app = {
        "id": "test-app",
        "aud": "test-audience",
        "name": DEPLOY.RESOURCE_NAME,
        "type": "self_hosted",
        "domain": DEPLOY.PREVIOUS_HOSTNAME,
        "destinations": [{"type": "public", "uri": DEPLOY.PREVIOUS_HOSTNAME}],
        "service_auth_401_redirect": True,
        "session_duration": "1h",
    }
    rule = {
        "hostname": DEPLOY.PREVIOUS_HOSTNAME,
        "service": "http://127.0.0.1:3333",
        "originRequest": {
            "access": {"required": True, "teamName": "test-team", "audTag": ["test-audience"]}
        },
    }
    config = {"ingress": [rule, {"service": "http_status:404"}], "warp-routing": {"enabled": False}}
    old = {
        "id": "old-record",
        "name": DEPLOY.PREVIOUS_HOSTNAME,
        "type": "CNAME",
        "content": "test-tunnel.cfargotunnel.com",
        "proxied": True,
        "ttl": 1,
        "comment": DEPLOY.RESOURCE_NAME,
    }
    state = {
        "app": app,
        "policies": [policy],
        "config": config,
        "old": [old],
        "new": [],
        "calls": [],
        "fail_public": False,
        "fail_finalize": False,
        "fail_discovery": False,
        "bic": None,
    }

    def api(method, path, body=None):
        state["calls"].append((method, path, copy.deepcopy(body)))
        if method == "GET":
            if path.endswith("/rulesets/phases/http_request_firewall_custom/entrypoint"):
                if state["bic"] is None:
                    raise urllib.error.HTTPError(path, 404, "not found", {}, None)
                return copy.deepcopy(state["bic"])
            if path == "/user":
                return {"id": DEPLOY.OWNER_USER_ID, "email": "owner@example.invalid"}
            if path.endswith("/access/identity_providers"):
                return [{"id": DEPLOY.CLOUDFLARE_IDP_ID, "type": "cloudflare"}]
            if path == f"/zones/{DEPLOY.ZONE_ID}":
                return {
                    "name": "zacks.vision",
                    "status": "active",
                    "account": {"id": "test-account"},
                }
            if path.endswith("/policies"):
                return copy.deepcopy(state["policies"])
            if path.endswith("/access/apps/test-app"):
                return copy.deepcopy(state["app"])
            if "access/apps?" in path:
                return [copy.deepcopy(state["app"])]
            if path.endswith("/configurations"):
                return {"config": copy.deepcopy(state["config"])}
            if "dns_records?" in path:
                return copy.deepcopy(state["new" if DEPLOY.ZONE_ID in path else "old"])
        if method == "PUT" and path.endswith("/access/apps/test-app"):
            if state["fail_finalize"] and body["domain"] == DEPLOY.HOSTNAME:
                raise RuntimeError("fake-private-secret")
            state["app"].update(copy.deepcopy(body))
            if body.get("oauth_configuration", {}).get("enabled") is False:
                state["app"]["oauth_configuration"].setdefault(
                    "dynamic_client_registration",
                    {
                        "enabled": True,
                        "allow_any_on_localhost": True,
                        "allow_any_on_loopback": True,
                    },
                )
            state["policies"] = state["app"].pop("policies")
            for policy in state["policies"]:
                policy.setdefault("id", "owner-policy-test")
            return copy.deepcopy(state["app"])
        if method == "POST" and path.endswith("/rulesets"):
            state["bic"] = {"id": "test-ruleset", **copy.deepcopy(body)}
            state["bic"]["rules"][0]["id"] = "test-bic-rule"
            return copy.deepcopy(state["bic"])
        if method == "POST" and path.endswith("/rulesets/test-ruleset/rules"):
            state["bic"]["rules"].append({"id": "test-bic-rule", **copy.deepcopy(body)})
            return copy.deepcopy(state["bic"])
        if method == "DELETE" and path.endswith("/rulesets/test-ruleset/rules/test-bic-rule"):
            state["bic"]["rules"] = [
                rule for rule in state["bic"]["rules"] if rule["id"] != "test-bic-rule"
            ]
            return {}
        if method == "DELETE" and path.endswith("/rulesets/test-ruleset"):
            assert not state["bic"]["rules"]
            state["bic"] = None
            return {}
        if method == "PUT" and path.endswith("/configurations"):
            state["config"] = copy.deepcopy(body["config"])
            return {}
        if method == "POST" and path.endswith("/dns_records"):
            key = "new" if DEPLOY.ZONE_ID in path else "old"
            record = {"id": key + "-record", **copy.deepcopy(body)}
            state[key] = [record]
            return record
        if method == "DELETE" and "/dns_records/" in path:
            state["new" if DEPLOY.ZONE_ID in path else "old"] = []
            return {}
        raise AssertionError((method, path))

    def public(credentials, *, hostname):
        state["calls"].append(("PROBE", hostname, None))
        if hostname == DEPLOY.HOSTNAME and state["fail_public"]:
            raise RuntimeError("fake-private-secret")
        key = "new" if hostname == DEPLOY.HOSTNAME else "old"
        assert state[key]
        assert {"type": "public", "uri": hostname} in state["app"]["destinations"]
        assert any(rule.get("hostname") == hostname for rule in state["config"]["ingress"])
        return {
            "anonymousDenied": True,
            "invalidCredentialDenied": True,
            "authenticatedMcpVerified": True,
        }

    monkeypatch.setattr(DEPLOY, "cf", api)
    monkeypatch.setattr(DEPLOY, "public_health", public)

    def discovery():
        state["calls"].append(("DISCOVERY", DEPLOY.HOSTNAME, None))
        if state["fail_discovery"]:
            raise RuntimeError("fake-private-secret")
        assert any(rule.get("ref") == DEPLOY.BIC_RULE["ref"] for rule in state["bic"]["rules"])
        return {"oauthDiscoveryVerified": True, "pkceS256Advertised": True}

    monkeypatch.setattr(DEPLOY, "verify_oauth_discovery", discovery)
    return credentials, state


def test_domain_preflight_is_readonly(cloudflare):
    credentials, state = cloudflare
    report = DEPLOY.migrate_domain(credentials, apply=False)
    assert report["ok"] and not report["applied"] and not report["domainReady"]
    assert all(method in {"GET", "PROBE"} for method, _, _ in state["calls"])


def test_domain_cutover_protects_before_dns_and_reuses_credentials(cloudflare):
    credentials, state = cloudflare
    original = copy.deepcopy(credentials)
    state["app"]["cors_headers"] = None
    report = DEPLOY.migrate_domain(credentials, apply=True)
    assert report["domainReady"] and report["oldDomainRetired"]
    assert not report["credentialsRotated"] and credentials == original
    assert not state["old"] and state["new"]
    assert state["app"]["domain"] == DEPLOY.HOSTNAME
    assert state["app"]["aud"] == "test-audience"
    assert state["policies"][0]["id"] == "policy-test"
    writes = [call for call in state["calls"] if call[0] not in {"GET", "PROBE"}]
    assert writes[0][1].endswith("/access/apps/test-app")
    assert "cors_headers" not in writes[0][2]
    assert writes[0][2]["destinations"] == [
        {"type": "public", "uri": host} for host in (DEPLOY.PREVIOUS_HOSTNAME, DEPLOY.HOSTNAME)
    ]
    assert writes[1][1].endswith("/configurations")
    assert writes[2][0] == "POST" and writes[2][1].endswith("/dns_records")
    probe = next(
        i for i, call in enumerate(state["calls"]) if call[:2] == ("PROBE", DEPLOY.HOSTNAME)
    )
    retirement = next(i for i, call in enumerate(state["calls"]) if call[0] == "DELETE")
    assert probe < retirement
    assert all("service_tokens" not in path for _, path, _ in state["calls"])
    state["calls"].clear()
    assert not DEPLOY.migrate_domain(credentials, apply=True)["applied"]
    assert all(method in {"GET", "PROBE"} for method, _, _ in state["calls"])


@pytest.mark.parametrize("failure", ["fail_public", "fail_finalize"])
def test_domain_failure_restores_previous_route_and_dns(cloudflare, failure):
    credentials, state = cloudflare
    original_app = copy.deepcopy(state["app"])
    original_config = copy.deepcopy(state["config"])
    state[failure] = True
    with pytest.raises(DEPLOY.DomainMigrationFailure) as caught:
        DEPLOY.migrate_domain(credentials, apply=True)
    assert caught.value.rollback_verified
    assert "fake-private-secret" not in str(caught.value)
    assert state["app"]["domain"] == original_app["domain"]
    assert state["app"]["destinations"] == original_app["destinations"]
    assert state["config"] == original_config
    assert state["old"] and not state["new"]


@pytest.mark.parametrize("conflict", ["policy", "dns", "ingress"])
def test_domain_refuses_unowned_or_weakened_configuration_before_writes(cloudflare, conflict):
    credentials, state = cloudflare
    if conflict == "policy":
        state["policies"][0]["include"] = [{"any_valid_service_token": {}}]
    elif conflict == "dns":
        state["new"] = [{**state["old"][0], "name": DEPLOY.HOSTNAME, "content": "foreign.example"}]
    else:
        state["config"]["ingress"].insert(
            0, {"hostname": "foreign.example", "service": "http://127.0.0.1:3000"}
        )
    with pytest.raises(RuntimeError, match="ownership_mismatch"):
        DEPLOY.migrate_domain(credentials, apply=True)
    assert all(method == "GET" for method, _, _ in state["calls"])


def test_domain_workflow_separates_runtime_and_operations_identity():
    workflow = yaml.load(
        (ROOT / ".github/workflows/production-appium-mcp.yml").read_text(), Loader=yaml.BaseLoader
    )
    inputs = workflow["on"]["workflow_dispatch"]["inputs"]
    assert {"domain_preflight", "domain_apply"} <= set(inputs["operation"]["options"])
    assert "runtime_commit" in inputs
    steps = workflow["jobs"]["operate"]["steps"]
    gate = next(step for step in steps if step.get("name") == "Require exact main commit and CI")
    assert '--target-commit "$RUNTIME_COMMIT"' in gate["run"]
    stage = next(step for step in steps if step.get("name", "").startswith("Stage locked"))
    assert stage["if"] == "inputs.operation == 'preflight' || inputs.operation == 'apply'"
    assert workflow["jobs"]["operate"]["environment"] == "production"


def canonical_domain(state):
    state["app"]["domain"] = DEPLOY.HOSTNAME
    state["app"]["destinations"] = [{"type": "public", "uri": DEPLOY.HOSTNAME}]
    state["config"]["ingress"][0]["hostname"] = DEPLOY.HOSTNAME
    state["new"] = [{**state["old"][0], "name": DEPLOY.HOSTNAME}]
    state["old"] = []


def test_oauth_preflight_is_readonly_and_resolves_owner_privately(cloudflare):
    credentials, state = cloudflare
    canonical_domain(state)
    report = DEPLOY.configure_oauth(credentials, apply=False)
    assert report["ownerIdentityVerified"] and not report["oauthReady"]
    assert not report["applied"] and not report["oauthLoginVerified"]
    assert all(method in {"GET", "PROBE"} for method, _, _ in state["calls"])
    assert "owner@example.invalid" not in json.dumps(report)


def test_oauth_preserves_runtime_routes_machine_policy_and_audience(cloudflare):
    credentials, state = cloudflare
    canonical_domain(state)
    original = copy.deepcopy(state)
    report = DEPLOY.configure_oauth(credentials, apply=True)
    assert report["oauthReady"] and report["oauthDiscoveryVerified"]
    assert not report["credentialsRotated"] and not report["oauthLoginVerified"]
    assert state["app"]["aud"] == original["app"]["aud"]
    assert state["config"] == original["config"]
    assert state["new"] == original["new"]
    assert state["policies"][0] == original["policies"][0]
    assert state["policies"][1] == {
        "id": "owner-policy-test",
        **DEPLOY.owner_policy("owner@example.invalid"),
    }
    assert state["app"]["allowed_idps"] == [DEPLOY.CLOUDFLARE_IDP_ID]
    assert state["app"]["oauth_configuration"] == DEPLOY.OAUTH_CONFIGURATION
    writes = [call for call in state["calls"] if call[0] not in {"GET", "PROBE", "DISCOVERY"}]
    assert len(writes) == 2
    assert writes[0][0] == "POST" and writes[0][1].endswith("/rulesets")
    assert writes[0][2]["rules"] == [DEPLOY.BIC_RULE]
    assert writes[1][:2] == (
        "PUT",
        "/accounts/test-account/access/apps/test-app",
    )
    state["calls"].clear()
    assert not DEPLOY.configure_oauth(credentials, apply=True)["applied"]
    assert all(method in {"GET", "PROBE", "DISCOVERY"} for method, _, _ in state["calls"])


def test_oauth_failed_acceptance_restores_exact_policy_set(cloudflare):
    credentials, state = cloudflare
    canonical_domain(state)
    original = copy.deepcopy(state)
    state["fail_discovery"] = True
    with pytest.raises(DEPLOY.OAuthConfigurationFailure) as caught:
        DEPLOY.configure_oauth(credentials, apply=True)
    assert caught.value.rollback_verified
    assert caught.value.stage == "verify_owner_oauth"
    assert "fake-private-secret" not in str(caught.value)
    assert state["policies"] == original["policies"]
    assert state["config"] == original["config"]
    assert not state["app"]["oauth_configuration"]["enabled"]
    assert state["app"]["oauth_configuration"]["dynamic_client_registration"]["enabled"]
    assert state["bic"] is None


@pytest.mark.parametrize(
    "selector",
    [
        {"everyone": {}},
        {"cloudflare_account": {"id": "test-account"}},
        {"email": {"email": "other@example.invalid"}},
    ],
)
def test_oauth_refuses_broad_or_foreign_user_policy_before_writes(cloudflare, selector):
    credentials, state = cloudflare
    canonical_domain(state)
    state["policies"].append(
        {**DEPLOY.owner_policy("owner@example.invalid"), "include": [selector]}
    )
    with pytest.raises(RuntimeError, match="ownership_mismatch"):
        DEPLOY.configure_oauth(credentials, apply=True)
    assert all(method == "GET" for method, _, _ in state["calls"])


def test_owner_resolves_only_pinned_accepted_member_when_user_read_is_unavailable(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")
    member = {
        "status": "accepted",
        "user": {"id": DEPLOY.OWNER_USER_ID, "email": "owner@example.invalid"},
    }

    def api(method, path):
        if path == "/user":
            raise urllib.error.HTTPError(path, 403, "private", {}, None)
        assert method == "GET" and path.endswith("/members?per_page=50")
        return [member, {"status": "accepted", "user": {"id": "other"}}]

    monkeypatch.setattr(DEPLOY, "cf", api)
    assert DEPLOY.owner_identity() == "owner@example.invalid"
    member["status"] = "pending"
    with pytest.raises(RuntimeError, match="owner_identity_unavailable"):
        DEPLOY.owner_identity()


def test_domain_keeps_owner_oauth_settings(cloudflare):
    credentials, state = cloudflare
    state["app"]["oauth_configuration"] = copy.deepcopy(DEPLOY.OAUTH_CONFIGURATION)
    state["policies"].append(
        {"id": "owner-policy-test", **DEPLOY.owner_policy("owner@example.invalid")}
    )
    DEPLOY.migrate_domain(credentials, apply=True)
    assert state["app"]["oauth_configuration"] == DEPLOY.OAUTH_CONFIGURATION
    assert len(state["policies"]) == 2


@pytest.mark.parametrize(
    "failure",
    [
        None,
        "resource",
        "issuer",
        "pkce",
        "endpoint",
        "challenge",
        "legacy",
        "alternate_path",
        "as_pointer",
    ],
)
def test_oauth_discovery_validates_challenge_resource_issuer_and_pkce(monkeypatch, failure):
    origin = f"https://{DEPLOY.HOSTNAME}"
    resource_url = origin + "/.well-known/oauth-protected-resource"
    if failure == "alternate_path":
        resource_url = origin + "/cdn-cgi/access/resource"
    issuer = f"https://{DEPLOY.TEAM_DOMAIN}/cdn-cgi/access/oauth"
    resource = {"resource": origin, "authorization_servers": [issuer]}
    server = {
        "issuer": issuer,
        "authorization_endpoint": issuer + "/authorize",
        "token_endpoint": issuer + "/token",
        "registration_endpoint": issuer + "/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
    }
    if failure == "resource":
        resource["resource"] = "https://foreign.invalid"
    if failure == "issuer":
        server["issuer"] += "/foreign"
    if failure == "pkce":
        server["code_challenge_methods_supported"] = ["plain"]
    if failure == "endpoint":
        server["token_endpoint"] = "https://foreign.invalid/token"
    challenge = f'Bearer resource_metadata="{resource_url}"'
    if failure == "legacy":
        challenge = 'Bearer realm="Access"'
    if failure == "challenge":
        challenge = 'Bearer resource_metadata="http://127.0.0.1/private"'

    class Opener:
        def open(self, request, timeout):
            assert timeout == 20
            if request.full_url == origin + "/mcp":
                headers = Message()
                headers["WWW-Authenticate"] = challenge
                raise urllib.error.HTTPError(request.full_url, 401, "unauthorized", headers, None)
            if request.full_url == resource_url:
                return io.BytesIO(
                    json.dumps(server if failure == "as_pointer" else resource).encode()
                )
            if failure == "legacy":
                assert request.full_url == origin + "/.well-known/oauth-authorization-server"
                return io.BytesIO(json.dumps(server).encode())
            assert (
                request.full_url
                == f"https://{DEPLOY.TEAM_DOMAIN}/.well-known/oauth-authorization-server/cdn-cgi/access/oauth"
            )
            return io.BytesIO(json.dumps(server).encode())

    monkeypatch.setattr(DEPLOY.urllib.request, "build_opener", lambda _: Opener())
    if failure not in {None, "legacy", "alternate_path", "as_pointer"}:
        with pytest.raises(RuntimeError, match="oauth_"):
            DEPLOY.oauth_discovery()
    else:
        assert DEPLOY.oauth_discovery()["oauthDiscoveryVerified"]


def test_bic_exception_skips_only_browser_integrity_for_the_dedicated_hostname():
    assert DEPLOY.BIC_RULE["expression"] == f'(http.host eq "{DEPLOY.HOSTNAME}")'
    assert DEPLOY.BIC_RULE["action_parameters"] == {"products": ["bic"]}
    assert DEPLOY.BIC_RULE["logging"] == {"enabled": True}
    assert DEPLOY.BIC_RULE["enabled"] is True


@pytest.mark.parametrize(
    "change",
    [
        {"expression": '(http.host contains "zacks.vision")'},
        {"action_parameters": {"products": ["bic", "waf"]}},
        {"action_parameters": {"products": ["bic"], "ruleset": "current"}},
        {"enabled": False},
    ],
)
def test_foreign_or_broadened_bic_rule_is_not_overwritten(cloudflare, change):
    credentials, state = cloudflare
    canonical_domain(state)
    state["bic"] = {
        "id": "test-ruleset",
        "kind": "zone",
        "phase": "http_request_firewall_custom",
        "rules": [{"id": "test-bic-rule", **DEPLOY.BIC_RULE, **change}],
    }
    with pytest.raises(RuntimeError, match="bic_ownership_mismatch"):
        DEPLOY.configure_oauth(credentials, apply=True)
    assert all(method == "GET" for method, _, _ in state["calls"])


def test_bic_rollback_preserves_unrelated_rules(cloudflare):
    credentials, state = cloudflare
    canonical_domain(state)
    unrelated = {"id": "keep-rule", "ref": "keep-rule", "action": "block"}
    state["bic"] = {
        "id": "test-ruleset",
        "kind": "zone",
        "phase": "http_request_firewall_custom",
        "rules": [unrelated],
    }
    state["fail_discovery"] = True
    with pytest.raises(DEPLOY.OAuthConfigurationFailure) as caught:
        DEPLOY.configure_oauth(credentials, apply=True)
    assert caught.value.rollback_verified
    assert state["bic"]["rules"] == [unrelated]
    assert not any(
        method == "DELETE" and path.endswith("/rulesets/test-ruleset")
        for method, path, _ in state["calls"]
    )


def test_bic_rollback_never_deletes_a_concurrently_populated_ruleset(cloudflare):
    _, state = cloudflare
    marker = DEPLOY.enable_bic_exception(DEPLOY.bic_snapshot())
    unrelated = {"id": "concurrent", "ref": "concurrent", "action": "block"}
    state["bic"]["rules"].append(unrelated)
    DEPLOY.restore_bic_exception(marker)
    assert state["bic"]["rules"] == [unrelated]


def test_disabled_oauth_defaults_are_semantically_restored_without_weakening_enabled_checks():
    assert DEPLOY.oauth_restored(
        {"enabled": False, "dynamic_client_registration": {"enabled": True}}, None
    )
    assert not DEPLOY.oauth_restored({"enabled": True}, None)
    assert not DEPLOY.oauth_restored({}, None)
    assert not DEPLOY.oauth_restored({"enabled": True}, DEPLOY.OAUTH_CONFIGURATION)
    assert DEPLOY.oauth_restored(DEPLOY.OAUTH_CONFIGURATION, DEPLOY.OAUTH_CONFIGURATION)


def test_oauth_failure_reports_only_fixed_nonsecret_reasons():
    assert (
        DEPLOY.OAuthConfigurationFailure(
            False, "probe", RuntimeError("oauth_challenge_missing")
        ).reason
        == "oauth_challenge_missing"
    )
    assert (
        DEPLOY.OAuthConfigurationFailure(False, "probe", RuntimeError("fake-private-secret")).reason
        is None
    )


def test_oauth_contract_is_owner_only_bounded_and_does_not_allow_arbitrary_https_callbacks():
    oauth = DEPLOY.OAUTH_CONFIGURATION
    assert oauth["grant"] == {"access_token_lifetime": "15m", "session_duration": "168h"}
    dcr = oauth["dynamic_client_registration"]
    assert dcr["enabled"] and dcr["allow_any_on_loopback"]
    assert dcr["allowed_uris"] == [
        "https://chatgpt.com/connector/oauth/*",
        "https://chatgpt.com/connector_platform_oauth_redirect",
    ]
    workflow = yaml.load(
        (ROOT / ".github/workflows/production-appium-mcp.yml").read_text(), Loader=yaml.BaseLoader
    )
    assert {"oauth_preflight", "oauth_apply"} <= set(
        workflow["on"]["workflow_dispatch"]["inputs"]["operation"]["options"]
    )
    steps = workflow["jobs"]["operate"]["steps"]
    assert "oauth_" in next(
        step["if"]
        for step in steps
        if step.get("name") == "Install public health probe dependencies"
    )
