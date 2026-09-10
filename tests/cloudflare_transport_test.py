from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from wechat_airflow.clients import cloudflare


@pytest.mark.parametrize(
    "host",
    [
        "-flag",
        "a.example;id",
        "https://a.example",
        "127.0.0.1",
        "a.example\n",
        "a.example/path",
        "a..example",
        "",
    ],
)
def test_proxy_rejects_non_dns_destinations(host):
    with pytest.raises(ValueError):
        cloudflare.proxy_argv(host)


def test_proxy_command_has_no_shell_or_credentials():
    assert cloudflare.proxy_argv("ssh.example.com") == [
        "cloudflared",
        "access",
        "ssh",
        "--hostname",
        "ssh.example.com",
        "--loglevel",
        "error",
    ]


def test_direct_transport_starts_no_process(monkeypatch):
    start = MagicMock()
    monkeypatch.setattr(cloudflare.subprocess, "Popen", start)
    assert cloudflare.ssh_proxy("127.0.0.1", "direct") is None
    start.assert_not_called()
    with pytest.raises(ValueError):
        cloudflare.ssh_proxy("ssh.example.com", "unknown")
    start.assert_not_called()


def test_partial_access_identity_fails_before_start(monkeypatch):
    start = MagicMock()
    monkeypatch.setattr(cloudflare.subprocess, "Popen", start)
    with pytest.raises(ValueError):
        cloudflare.CloudflareProxy(
            "ssh.example.com", environment={"TUNNEL_SERVICE_TOKEN_ID": "test-id"}
        )
    start.assert_not_called()


def process_stub(monkeypatch):
    process = MagicMock()
    process.poll.return_value = None
    process.stdin.closed = False
    process.stdout.closed = False
    monkeypatch.setattr(cloudflare.subprocess, "Popen", MagicMock(return_value=process))
    return process


def test_access_identity_only_enters_child_environment(monkeypatch):
    process_stub(monkeypatch)
    environment = {
        "PATH": "/bin",
        "TUNNEL_SERVICE_TOKEN_ID": "test-id",
        "TUNNEL_SERVICE_TOKEN_SECRET": "test-secret",
    }
    proxy = cloudflare.CloudflareProxy("ssh.example.com", environment=environment)
    kwargs = cloudflare.subprocess.Popen.call_args.kwargs
    assert kwargs["env"] == environment
    assert kwargs["env"] is not environment
    assert kwargs["stderr"] == subprocess.DEVNULL
    assert "test-secret" not in " ".join(proxy.cmd)
    assert kwargs.get("shell", False) is False


def test_eof_is_returned_without_spin(monkeypatch):
    process = process_stub(monkeypatch)
    proxy = cloudflare.CloudflareProxy("ssh.example.com", environment={})
    monkeypatch.setattr(
        cloudflare.select, "select", MagicMock(return_value=([process.stdout], [], []))
    )
    read = MagicMock(return_value=b"")
    monkeypatch.setattr(cloudflare.os, "read", read)
    assert proxy.recv(1024) == b""
    assert read.call_count == 1


def test_partial_pipe_write_reports_actual_count(monkeypatch):
    process = process_stub(monkeypatch)
    proxy = cloudflare.CloudflareProxy("ssh.example.com", environment={})
    monkeypatch.setattr(
        cloudflare.select, "select", MagicMock(return_value=([], [process.stdin], []))
    )
    monkeypatch.setattr(cloudflare.os, "write", MagicMock(return_value=2))
    assert proxy.send(b"abcdef") == 2


def test_close_is_idempotent_after_child_exit(monkeypatch):
    process = process_stub(monkeypatch)
    process.poll.return_value = 0
    proxy = cloudflare.CloudflareProxy("ssh.example.com", environment={})
    proxy.close()
    proxy.close()
    process.terminate.assert_not_called()
    assert proxy.closed


def test_close_reaps_stubborn_child(monkeypatch):
    process = process_stub(monkeypatch)
    process.wait.side_effect = [subprocess.TimeoutExpired("cloudflared", 2), 0]
    proxy = cloudflare.CloudflareProxy("ssh.example.com", environment={})
    proxy.close()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.wait.call_count == 2
