from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import device_network_preflight as probe  # noqa: E402
import install_cloudflared as installer  # noqa: E402


def test_health_summary_never_echoes_response_secrets():
    body = {"ok": True, "deploymentCommit": "a" * 40, "password": "do-not-log", "token": "private"}
    assert probe.health_summary(200, body)["commit"] == "a" * 40
    assert "do-not-log" not in json.dumps(probe.health_summary(200, body))
    assert probe.health_summary(302, body)["ok"] is False
    assert probe.health_summary(200, [body])["ok"] is False
    assert probe.health_summary(200, {"deploymentCommit": "secret"})["commit"] is None


def test_remote_probe_is_valid_python_and_does_not_write_or_send():
    compile(probe.HOST_PROBE, "host-probe", "exec")
    for forbidden in (
        "Variable.set",
        "requests.post",
        "/v1/wechat/send",
        "DELETE ",
        "UPDATE ",
        "INSERT ",
    ):
        assert forbidden not in probe.HOST_PROBE


def test_ssh_failure_does_not_echo_stderr_or_configuration():
    remote = {
        "repository_path": "/root/project",
        "host": "host",
        "port": "22",
        "username": "user",
    }
    result = subprocess.CompletedProcess([], 255, "", "secret-password-and-host")
    with (
        patch.object(probe, "airflow_remote", return_value=remote),
        patch.object(probe, "run", return_value=result),
    ):
        report = probe.host_inventory("a" * 40)
    assert report == {"ok": False, "reason": "host_inventory_failed", "exitCode": 255}


def test_channel_probe_is_get_only_and_closes_on_decode_failure():
    transport = MagicMock()
    channel = transport.open_channel.return_value
    connection = MagicMock()
    connection.getresponse.return_value.read.return_value = b"invalid"
    with (
        patch.object(probe.http.client, "HTTPConnection", return_value=connection),
        pytest.raises(ValueError),
    ):
        probe.read_channel_health(transport, 7001)
    transport.open_channel.assert_called_once_with(
        "direct-tcpip", ("127.0.0.1", 7001), ("127.0.0.1", 0), timeout=15
    )
    connection.request.assert_called_once_with("GET", "/readyz")
    connection.close.assert_called_once()
    channel.close.assert_called_once()


def test_channel_probe_bounds_response_size():
    connection = MagicMock()
    connection.getresponse.return_value.read.return_value = b"x" * (probe.MAX_RESPONSE_BYTES + 1)
    with patch.object(probe.http.client, "HTTPConnection", return_value=connection):
        report = probe.read_channel_health(MagicMock(), 8788)
    assert report == {"ok": False, "reason": "oversized_response"}
    connection.request.assert_called_once_with("GET", "/healthz")


def test_invalid_hostname_is_rejected_before_starting_proxy():
    with pytest.raises(probe.OpsError, match="invalid public SSH hostname"):
        probe.tunnel_inventory("host; echo credentials")


def test_tunnel_missing_credentials_never_starts_login():
    with patch.dict(probe.os.environ, {}, clear=True):
        assert probe.tunnel_inventory("ssh.example.test")["reason"] == "protected_pi_credentials_missing"


def test_installer_verifies_download_before_replacing_existing_file(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    valid = b"verified-binary"
    (config / "device-network.json").write_text(
        json.dumps(
            {
                "cloudflared": {
                    "version": "2026.9.0",
                    "linux-amd64": hashlib.sha256(valid).hexdigest(),
                }
            }
        )
    )
    target = tmp_path / "cloudflared"
    target.write_bytes(b"old-binary")
    with (
        patch.object(installer, "ROOT", tmp_path),
        patch.object(installer.platform, "system", return_value="Linux"),
        patch.object(installer.platform, "machine", return_value="x86_64"),
    ):
        with (
            patch.object(installer, "urlopen", return_value=io.BytesIO(b"corrupt")),
            pytest.raises(RuntimeError, match="digest mismatch"),
        ):
            installer.install(target)
        assert target.read_bytes() == b"old-binary"
        with patch.object(installer, "urlopen", return_value=io.BytesIO(valid)):
            installer.install(target)
        assert target.read_bytes() == valid
        assert target.stat().st_mode & 0o777 == 0o755
        with patch.object(installer, "urlopen") as download:
            installer.install(target)
            download.assert_not_called()


def test_workflow_uses_protected_exact_sha_read_only_entrypoint():
    source = (ROOT / ".github/workflows/production-device-network.yml").read_text()
    assert "environment: production" in source
    assert "scripts/github_release_gate.py" in source
    assert "pull_request:" not in source and "push:" not in source
    assert "DEVICE_TUNNEL_ACCESS_CLIENT_SECRET" in source
    assert "secret set" not in source
    assert "frpc" not in source
    router = (ROOT / ".github/workflows/ops-chatops.yml").read_text()
    assert "github.event.comment.user.login == github.repository_owner" in router
    assert '["/ops", "device-network-preflight"]' in router
    assert "needs.device_network_preflight.result" in router
