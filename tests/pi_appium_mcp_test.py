from __future__ import annotations

import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "pi_mcp_install", ROOT / "pi_host/appium_mcp/install.py"
)
assert SPEC and SPEC.loader
INSTALL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALL)
DEPLOY_SPEC = importlib.util.spec_from_file_location(
    "pi_mcp_deploy", ROOT / "scripts/deploy_pi_appium_mcp.py"
)
assert DEPLOY_SPEC and DEPLOY_SPEC.loader
DEPLOY = importlib.util.module_from_spec(DEPLOY_SPEC)
DEPLOY_SPEC.loader.exec_module(DEPLOY)


@pytest.mark.parametrize("name,link", [("../outside", ""), ("link", "../../outside")])
def test_installer_rejects_escaping_archives(tmp_path, name, link):
    archive = tmp_path / "archive.tar"
    with tarfile.open(archive, "w") as handle:
        entry = tarfile.TarInfo(name)
        if link:
            entry.type = tarfile.SYMTYPE
            entry.linkname = link
            handle.addfile(entry)
        else:
            entry.size = 1
            handle.addfile(entry, io.BytesIO(b"x"))
    with pytest.raises(ValueError, match="unsafe_archive"):
        INSTALL.unpack(archive, tmp_path / "destination")
    assert not (tmp_path / "outside").exists()


def test_mcp_workflow_preserves_exact_commit_environment_and_ssh_pinning():
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-appium-mcp.yml").read_text())
    job = workflow["jobs"]["operate"]
    assert job["environment"] == "production"
    assert job["if"] == "github.ref == 'refs/heads/main'"
    steps = job["steps"]
    assert any("github_release_gate.py" in step.get("run", "") for step in steps)
    stage = next(step["run"] for step in steps if step.get("name", "").startswith("Stage locked"))
    assert "npm ci --ignore-scripts --omit=optional" in stage
    assert INSTALL.NODE_SHA in stage
    assert "sha256sum --check" in stage
    runner = (ROOT / "scripts/deploy_pi_appium_mcp.py").read_text()
    assert '"non_identity"' in runner
    assert '"audTag": [app["aud"]]' in runner
    assert '"service_auth_401_redirect": True' in runner
    assert "hmac.compare_digest" in runner
    installer = (ROOT / "pi_host/appium_mcp/install.py").read_text()
    assert "tunnel --config %d/tunnel_config --no-autoupdate run --token-file" in installer
    assert "AutoAddPolicy" not in runner
    assert "send/v1" not in runner


def test_service_is_single_process_private_and_uses_existing_device_group():
    unit = (ROOT / "pi_host/appium_mcp/pi-appium-mcp.service").read_text()
    assert "SupplementaryGroups=wechat-sender" in unit
    assert "ReadWritePaths=/run/wechat-device" in unit
    assert "LoadCredential=devices.json:" in unit
    assert "KillMode=mixed" in unit
    assert unit.count("ExecStart=") == 1
    assert "--workers" not in unit
    server = (ROOT / "pi_host/appium_mcp/server.mjs").read_text()
    assert 'host: "127.0.0.1"' in server


def test_cloudflare_provision_orders_auth_before_public_dns(monkeypatch):
    calls = []
    secrets_saved = []
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "test-account")

    def api(method, path, body=None):
        calls.append((method, path, body))
        if method == "GET" and (
            "?per_page=" in path or "?is_deleted=" in path or "dns_records?" in path
        ):
            return []
        if path.endswith("/access/apps"):
            return {"id": "app-test", "aud": "audience-test"}
        if path.endswith("/access/service_tokens"):
            return {"id": "token-test", "client_id": "fake-client", "client_secret": "fake-secret"}
        if path.endswith("/access/organizations"):
            return {"auth_domain": "test-team.cloudflareaccess.com"}
        if path.endswith("/token"):
            return "fake-tunnel-token"
        if path.endswith("/cfd_tunnel"):
            return {"id": "tunnel-test"}
        if path.endswith("/cfd_tunnel/tunnel-test"):
            return {"status": "healthy"}
        return {}

    def ssh(client, command, payload="", **kwargs):
        if "cloudflare.json" in command:
            return "{}"
        if " credentials " in command:
            secrets_saved.append(payload)
        return '{"ok":true}'

    monkeypatch.setattr(DEPLOY, "cf", api)
    monkeypatch.setattr(DEPLOY, "remote", ssh)
    credentials = DEPLOY.provision(object(), "/fake/installer.py", "a" * 40)
    assert credentials["access_client_secret"] == "fake-secret"
    assert len(secrets_saved) == 1
    policy = next(i for i, call in enumerate(calls) if call[1].endswith("/policies"))
    connector = next(i for i, call in enumerate(calls) if call[1].endswith("/configurations"))
    dns = next(
        i for i, call in enumerate(calls) if call[0] == "POST" and call[1].endswith("/dns_records")
    )
    assert policy < connector < dns
    assert calls[policy][2]["include"] == [{"service_token": {"token_id": "token-test"}}]
    ingress = calls[connector][2]["config"]["ingress"]
    assert ingress[0]["originRequest"]["access"] == {
        "required": True,
        "teamName": "test-team",
        "audTag": ["audience-test"],
    }
    assert ingress[-1] == {"service": "http_status:404"}


def test_locked_service_excludes_unpatched_zip_chain_and_keeps_audit_gates():
    lock = json.loads((ROOT / "pi_host/appium_mcp/package-lock.json").read_text())
    assert not any("node_modules/extract-zip" in path for path in lock["packages"])
    for name in ("ci.yml", "production-appium-mcp.yml"):
        assert "npm run audit:runtime" in (ROOT / ".github/workflows" / name).read_text()
