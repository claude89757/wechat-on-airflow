from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import pi_ssh_auth  # noqa: E402

PI_SCRIPTS = (
    "deploy_pi_ydmap.py",
    "deploy_pi_appium_mcp.py",
    "deploy_remote_ops_mcp.py",
    "diagnose_pi_tunnel.py",
    "device_network_preflight.py",
)
PI_WORKFLOWS = (
    "production-airflow.yml",
    "production-appium-mcp.yml",
    "production-device-network.yml",
    "production-pi-tunnel-diagnose.yml",
    "production-pi-ydmap.yml",
    "production-remote-ops-mcp.yml",
)


def ed25519_pem() -> str:
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()


class FakeClient:
    """Records each connect call; outcomes are consumed in order."""

    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []
        self.closed = 0

    def connect(self, hostname: str, **kwargs: Any) -> None:
        self.calls.append({"hostname": hostname, **kwargs})
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome

    def close(self) -> None:
        self.closed += 1


def login(client: FakeClient, env: dict[str, str], **options: Any) -> str:
    return pi_ssh_auth.connect_from_env(
        client,  # type: ignore[arg-type]
        "pi.example",
        22,
        "pi-user",
        env=env,
        **options,
    )


def test_a_configured_key_is_used_without_touching_the_password() -> None:
    client = FakeClient([None])

    method = login(
        client, {"PI_DEVICE_SSH_PRIVATE_KEY": ed25519_pem(), "PI_DEVICE_SSH_PASSWORD": "pw"}
    )

    assert method == "publickey"
    assert len(client.calls) == 1
    assert isinstance(client.calls[0]["pkey"], paramiko.PKey)
    assert "password" not in client.calls[0]
    assert client.calls[0]["allow_agent"] is False and client.calls[0]["look_for_keys"] is False


def test_a_rejected_key_falls_back_to_the_password_on_a_fresh_connection() -> None:
    client = FakeClient([paramiko.AuthenticationException("denied"), None])

    method = login(
        client, {"PI_DEVICE_SSH_PRIVATE_KEY": ed25519_pem(), "PI_DEVICE_SSH_PASSWORD": "pw"}
    )

    assert method == "password"
    assert [("pkey" in call, "password" in call) for call in client.calls] == [
        (True, False),
        (False, True),
    ]
    assert client.closed == 1


def test_a_rejected_key_without_a_password_is_an_authentication_failure() -> None:
    client = FakeClient([paramiko.AuthenticationException("denied")])

    with pytest.raises(paramiko.AuthenticationException):
        login(client, {"PI_DEVICE_SSH_PRIVATE_KEY": ed25519_pem()})

    assert len(client.calls) == 1


def test_a_network_failure_is_never_retried_with_the_password() -> None:
    client = FakeClient([TimeoutError("slow")])

    with pytest.raises(TimeoutError):
        login(client, {"PI_DEVICE_SSH_PRIVATE_KEY": ed25519_pem(), "PI_DEVICE_SSH_PASSWORD": "pw"})

    assert len(client.calls) == 1


def test_a_host_key_mismatch_is_never_retried_with_the_password() -> None:
    client = FakeClient([paramiko.SSHException("host_key_mismatch")])

    with pytest.raises(paramiko.SSHException):
        login(client, {"PI_DEVICE_SSH_PRIVATE_KEY": ed25519_pem(), "PI_DEVICE_SSH_PASSWORD": "pw"})

    assert len(client.calls) == 1


def test_a_proxy_socket_is_not_reused_for_a_password_retry() -> None:
    client = FakeClient([paramiko.AuthenticationException("denied")])

    with pytest.raises(paramiko.AuthenticationException):
        login(
            client,
            {"PI_DEVICE_SSH_PRIVATE_KEY": ed25519_pem(), "PI_DEVICE_SSH_PASSWORD": "pw"},
            sock=object(),
        )

    assert len(client.calls) == 1


def test_an_unusable_key_uses_the_password_and_without_one_fails() -> None:
    client = FakeClient([None])
    assert login(
        client, {"PI_DEVICE_SSH_PRIVATE_KEY": "not a key", "PI_DEVICE_SSH_PASSWORD": "pw"}
    ) == ("password")

    with pytest.raises(paramiko.SSHException, match="pi_ssh_key_unusable"):
        login(FakeClient([None]), {"PI_DEVICE_SSH_PRIVATE_KEY": "not a key"})


def test_password_only_environment_still_works_during_migration() -> None:
    client = FakeClient([None])

    assert login(client, {"PI_DEVICE_SSH_PASSWORD": "pw"}) == "password"
    assert client.calls[0]["password"] == "pw" and "pkey" not in client.calls[0]


def test_missing_credentials_are_refused_before_any_connection() -> None:
    client = FakeClient([])

    assert pi_ssh_auth.has_credentials({}) is False
    assert pi_ssh_auth.has_credentials({"PI_DEVICE_SSH_PRIVATE_KEY": "  "}) is False
    assert pi_ssh_auth.has_credentials({"PI_DEVICE_SSH_PRIVATE_KEY": "x"}) is True
    with pytest.raises(RuntimeError, match="pi_ssh_credentials_missing"):
        login(client, {})
    assert client.calls == []


def test_every_pi_script_logs_in_through_the_key_first_helper() -> None:
    for name in PI_SCRIPTS:
        source = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "connect_from_env(" in source, name
        assert 'password=os.environ["PI_DEVICE_SSH_PASSWORD"]' not in source, name
        assert 'os.environ["PI_DEVICE_SSH_PASSWORD"]' not in source, name


def test_every_workflow_that_passes_the_pi_password_also_passes_the_key() -> None:
    for name in PI_WORKFLOWS:
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert re.search(
            r"PI_DEVICE_SSH_PASSWORD: \$\{\{ secrets\.PI_DEVICE_SSH_PASSWORD \}\}", text
        )
        assert re.search(
            r"PI_DEVICE_SSH_PRIVATE_KEY: \$\{\{ secrets\.PI_DEVICE_SSH_PRIVATE_KEY \}\}", text
        ), name
