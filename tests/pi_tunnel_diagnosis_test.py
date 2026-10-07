from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "pi_tunnel_diagnosis", ROOT / "scripts/diagnose_pi_tunnel.py"
)
assert spec and spec.loader
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_remote_output_has_closed_allowlist():
    raw = {
        "readOnly": True,
        "uptimeSeconds": 42,
        "rootFreeBytes": 1234,
        "secret": "do-not-print",
        "systemd": [
            {
                "ActiveState": "active",
                "Result": "secret-value",
                "ExecMainStatus": "0",
                "rawLogs": "token=secret",
                "logCategories": {"timeout": 2, "secret": 99},
            }
        ],
        "docker": [],
    }
    result = probe.safe_report(raw)
    rendered = json.dumps(result)
    assert "secret" not in rendered
    assert result["systemd"][0]["ActiveState"] == "active"
    assert result["systemd"][0]["Result"] == "unknown"
    assert result["systemd"][0]["logCategories"]["timeout"] == 2


@pytest.mark.parametrize("value", [-1, True, "-1", "secret", 10**19, None])
def test_non_numeric_values_are_not_forwarded(value):
    assert probe.bounded_int(value) is None


def test_remote_probe_has_only_bounded_read_commands(monkeypatch, capsys):
    calls = []

    def run(argv):
        calls.append(argv)
        if argv[:2] == ["systemctl", "list-units"]:
            out = b"cloudflared.service loaded active running\n"
        elif argv[:2] == ["systemctl", "show"]:
            out = b"ActiveState=active\nResult=success\nExecMainStatus=0\n"
        elif argv[0] == "journalctl":
            out = b"timeout token=SUPERSECRET\nregistered tunnel connection\n"
        elif argv[:2] == ["docker", "ps"]:
            out = b"abc123abc123\tcloudflare/cloudflared:latest\tcloudflared-secret-name\n"
        elif argv[:2] == ["docker", "inspect"]:
            out = b'"running"|true|false|0|2\n'
        else:
            out = b"connection refused token=SUPERSECRET\n"
        return 0, out.decode()

    namespace = {}
    exec(probe.REMOTE_PROBE.removesuffix("collect()\n"), namespace)
    namespace["command"] = run
    namespace["collect"]()
    rendered = capsys.readouterr().out
    assert "SUPERSECRET" not in rendered
    assert "secret-name" not in rendered
    assert "abc123abc123" not in rendered
    result = probe.safe_report(json.loads(rendered))
    assert result["systemd"][0]["logCategories"]["timeout"] == 1
    assert result["docker"][0]["restartCount"] == 2
    assert all(command[0] in {"systemctl", "journalctl", "docker"} for command in calls)
    assert all(
        command[1] in {"list-units", "show", "ps", "inspect", "logs", "--no-pager"}
        for command in calls
    )


def fake_paramiko(monkeypatch, fingerprint_key=b"trusted-host-key", mismatch=False):
    class SSHException(Exception):
        pass

    client = Mock()
    key = SimpleNamespace(asbytes=lambda: b"wrong-key" if mismatch else fingerprint_key)
    policy = []
    client.set_missing_host_key_policy.side_effect = policy.append
    client.connect.side_effect = lambda **kwargs: policy[0].missing_host_key(
        client, kwargs["hostname"], key
    )
    stdout = Mock()
    stdout.read.return_value = b'{"readOnly":true,"systemd":[],"docker":[]}'
    stdout.channel.recv_exit_status.return_value = 0
    client.exec_command.return_value = (Mock(), stdout, Mock())
    monkeypatch.setitem(
        sys.modules,
        "paramiko",
        SimpleNamespace(
            MissingHostKeyPolicy=object, SSHException=SSHException, SSHClient=lambda: client
        ),
    )
    values = {
        "PI_DEVICE_SSH_HOST": "private-host",
        "PI_DEVICE_SSH_PORT": "6000",
        "PI_DEVICE_SSH_USER": "private-user",
        "PI_DEVICE_SSH_PASSWORD": "SUPERSECRET",
        "PI_DEVICE_SSH_HOST_KEY_SHA256": "SHA256:"
        + base64.b64encode(hashlib.sha256(fingerprint_key).digest()).decode().rstrip("="),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return client


def test_host_pin_mismatch_fails_before_command(monkeypatch, capsys):
    client = fake_paramiko(monkeypatch, mismatch=True)
    assert probe.main() == 1
    client.exec_command.assert_not_called()
    text = capsys.readouterr().out
    assert "SUPERSECRET" not in text and "private-host" not in text
    assert json.loads(text)["sshAuthenticated"] is False


def test_authenticated_probe_has_no_agent_or_key_fallback(monkeypatch, capsys):
    client = fake_paramiko(monkeypatch)
    assert probe.main() == 0
    kwargs = client.connect.call_args.kwargs
    assert kwargs["look_for_keys"] is False and kwargs["allow_agent"] is False
    assert client.exec_command.call_args.args == ("python3 -",)
    result = capsys.readouterr().out
    assert "SUPERSECRET" not in result and "private-host" not in result
    assert json.loads(result)["configurationChanged"] is False


def test_exception_messages_never_escape(monkeypatch, capsys):
    client = fake_paramiko(monkeypatch)
    client.connect.side_effect = RuntimeError("SUPERSECRET private-host")
    assert probe.main() == 1
    text = capsys.readouterr().out
    assert "SUPERSECRET" not in text and "private-host" not in text


def test_workflow_is_manual_protected_and_exact_commit_gated():
    workflow = (ROOT / ".github/workflows/production-pi-tunnel-diagnose.yml").read_text()
    assert "environment: production" in workflow
    assert "contents: read" in workflow
    assert "schedule:" not in workflow
    assert "github_release_gate.py" in workflow
    assert "--wait-seconds 0" in workflow
    assert "PI_DEVICE_SSH_HOST_KEY_SHA256" in workflow
    assert "CLOUDFLARE_API_TOKEN" not in workflow
    assert "deploy_apply" not in workflow
    router = (ROOT / ".github/workflows/ops-chatops.yml").read_text()
    assert 'tokens[:2] == ["/ops", "pi-tunnel-diagnose"]' in router
    assert "github.event.comment.user.login == github.repository_owner" in router


def test_remote_command_enforces_output_cap():
    namespace = {}
    exec(probe.REMOTE_PROBE.removesuffix("collect()\n"), namespace)
    code, output = namespace["command"]([sys.executable, "-c", "print('x' * 2100000)"])
    assert code == -1 and output == ""


def test_remote_deadline_does_not_start_more_commands(monkeypatch):
    namespace = {}
    exec(probe.REMOTE_PROBE.removesuffix("collect()\n"), namespace)
    namespace["DEADLINE"] = 0
    process = Mock(side_effect=AssertionError("must not spawn"))
    monkeypatch.setattr("subprocess.Popen", process)
    assert namespace["command"](["systemctl", "show", "cloudflared.service"]) == (-1, "")
    process.assert_not_called()


def test_log_categories_use_linear_substring_matching():
    namespace = {}
    exec(probe.REMOTE_PROBE.removesuffix("collect()\n"), namespace)
    counts = namespace["categories"]("dns " * 500000)
    assert counts["dns_failure"] == 0
    assert "re.search" not in probe.REMOTE_PROBE
