from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "remote_ops_deploy_test", ROOT / "scripts/deploy_remote_ops_mcp.py"
)
assert SPEC and SPEC.loader
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


def test_existing_membership_is_never_written(monkeypatch):
    calls = []

    def cf(method, path, body=None):
        calls.append(method)
        return [
            {
                "id": "owned-group",
                "name": "Zacks Pi administrators",
                "include": [{"email": {"email": "private@example.test"}}],
            }
        ]

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test")
    monkeypatch.setattr(DEPLOY.phone, "cf", cf)
    assert DEPLOY.group("Zacks Pi administrators", True) == "owned-group"
    assert calls == ["GET"]


@pytest.mark.parametrize("root,expected", [(True, "python3"), (False, "sudo -n python3")])
def test_host_authority_uses_root_directly_without_requiring_sudo(monkeypatch, root, expected):
    monkeypatch.setattr(DEPLOY, "ROOT_PYTHON", "sudo -n python3")
    monkeypatch.setattr(
        DEPLOY.phone,
        "remote",
        lambda *a: json.dumps(
            {
                "rootLogin": root,
                "pythonVersion": [3, 6, 9],
                "sudoAvailable": not root,
            }
        ),
    )
    assert DEPLOY.host_environment(object())["rootLogin"] is root
    assert DEPLOY.ROOT_PYTHON == expected


def test_host_installer_preserves_legacy_python_and_withdrawal_contract():
    source = (ROOT / "pi_host/remote_ops/install.py").read_text()
    assert "from __future__ import annotations" not in source
    assert "capture_output=True" not in source
    assert "missing_ok=True" not in source
    assert ".is_relative_to(" not in source
    commands = [
        [item.value for item in node.elts]
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.List) and all(isinstance(item, ast.Constant) for item in node.elts)
    ]
    assert [
        "systemctl",
        "disable",
        "--now",
        "zacks-ops-mcp.service",
        "cloudflared-ops-mcp.service",
    ] in commands
    assert '"originPortAvailableOrOwned"' in source
    deploy = (
        (ROOT / "scripts/deploy_remote_ops_mcp.py")
        .read_text()
        .split('prefix = f"{ROOT_PYTHON} {installer}"')[1]
    )
    assert deploy.index('if operation == "withdraw":') < deploy.index("preflight =")


def test_inactive_failed_first_install_can_be_recovered(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "ops_install_test", ROOT / "pi_host/remote_ops/install.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    connector = tmp_path / "connector.service"
    connector.touch()
    monkeypatch.setattr(module, "BASE", tmp_path / "base")
    monkeypatch.setattr(module, "CONFIG", tmp_path / "config")
    monkeypatch.setattr(module, "Path", lambda path: connector)
    calls = []

    def run(command):
        calls.append(command)
        return "inactive\n" if "show" in command else ""

    monkeypatch.setattr(module, "run", run)
    monkeypatch.setattr(module, "health", lambda: pytest.fail("inactive runtime has no listener"))
    monkeypatch.setattr(module, "activate", lambda *args: {"ok": True})
    assert module.install(object(), {}) == {"ok": True}
    assert any("show" in command for command in calls)


def test_preflight_does_not_create_group(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test")
    monkeypatch.setattr(DEPLOY.phone, "cf", lambda method, path: [])
    assert DEPLOY.group("Zacks Pi administrators", False) is None


def test_ambiguous_group_fails_closed(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test")
    monkeypatch.setattr(
        DEPLOY.phone, "cf", lambda *a: [{"id": str(n), "name": "duplicate"} for n in range(2)]
    )
    with pytest.raises(RuntimeError):
        DEPLOY.group("duplicate", True)


def test_policy_is_exact_group_and_identity_provider():
    policy = DEPLOY.group_policy("group-id", "operators")
    assert policy["include"] == [{"group": {"id": "group-id"}}]
    assert policy["require"] == [{"login_method": {"id": DEPLOY.phone.CLOUDFLARE_IDP_ID}}]
    assert "everyone" not in json.dumps(policy)


def test_production_workflow_has_exact_sha_and_environment_gates():
    workflow = yaml.load(
        (ROOT / ".github/workflows/production-remote-ops-mcp.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    job = workflow["jobs"]["operate"]
    assert job["environment"] == "production"
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert "issue_comment" not in workflow["on"]
    gate = next(
        step for step in job["steps"] if step.get("name") == "Require exact main commit and CI"
    )
    assert "github_release_gate.py" in gate["run"]
    assert "merge-base --is-ancestor" in gate["run"]


def test_mcp_never_registers_approval_tool():
    source = (ROOT / "pi_host/remote_ops/server.mjs").read_text()
    assert 'registerTool("approve' not in source
    assert "req.headers.authorization || !cookie.CF_Authorization" in source
    assert 'algorithms: ["RS256"]' in source
    assert "audience: config.audience" in source
    assert '.listen(config.port || 3340, "127.0.0.1")' in source
    assert "req.headers.origin === config.origin" in source


def test_cloudflare_admin_credential_not_installed_on_hosts():
    source = (ROOT / "scripts/deploy_remote_ops_mcp.py").read_text()
    assert '"CLOUDFLARE_API_TOKEN"' not in source
    assert "mcp.cloudflare.com/mcp" in (ROOT / "pi_host/remote_ops/server.mjs").read_text()


def test_phone_group_coexists_with_owner_and_machine(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test")
    monkeypatch.setattr(DEPLOY.phone, "owner_identity", lambda: "owner@example.test")
    monkeypatch.setattr(
        DEPLOY.phone, "cf", lambda *a: [{"id": "phone-group", "name": "Zacks phone operators"}]
    )
    machine = {
        "decision": "non_identity",
        "include": [{"service_token": {"token_id": "health"}}],
        "exclude": [],
        "require": [],
    }
    owner = DEPLOY.phone.owner_policy("owner@example.test")
    collaborator = DEPLOY.group_policy("phone-group", "Zacks phone operators", 3)
    DEPLOY.phone.validate_access_policies([machine, owner, collaborator], {"token_id": "health"})
    with pytest.raises(RuntimeError):
        DEPLOY.phone.validate_access_policies([machine, collaborator], {"token_id": "health"})
    collaborator["include"] = [{"everyone": {}}]
    with pytest.raises(RuntimeError):
        DEPLOY.phone.validate_access_policies(
            [machine, owner, collaborator], {"token_id": "health"}
        )
