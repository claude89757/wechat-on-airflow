from __future__ import annotations

import copy
import importlib.util
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
    }

    def api(method, path, body=None):
        state["calls"].append((method, path, copy.deepcopy(body)))
        if method == "GET":
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
            state["policies"] = state["app"].pop("policies")
            return copy.deepcopy(state["app"])
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
