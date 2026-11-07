from __future__ import annotations

import io
import sys
from pathlib import Path

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from wechat_airflow.clients import pi_device
from wechat_airflow.venues import dsh_ydmap_client as dsh_client

HOST_KEY = "SHA256:" + "A" * 43
ROOT = Path(__file__).resolve().parents[1]


def ed25519_pem() -> str:
    key = ed25519.Ed25519PrivateKey.generate()
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()


class FakeStream:
    def __init__(self, text: str, status: int = 0) -> None:
        self._text = text
        self.channel = self
        self._status = status

    def recv_exit_status(self) -> int:
        return self._status

    def read(self) -> bytes:
        return self._text.encode()


class FakeClient:
    instances: list[FakeClient] = []
    outcomes: list[BaseException | None] = []

    def __init__(self) -> None:
        self.connect_kwargs: dict[str, object] = {}
        self.closed = False
        FakeClient.instances.append(self)

    def set_missing_host_key_policy(self, policy: object) -> None:
        del policy

    def connect(self, **kwargs: object) -> None:
        self.connect_kwargs = kwargs
        outcome = FakeClient.outcomes.pop(0) if FakeClient.outcomes else None
        if outcome is not None:
            raise outcome

    def exec_command(self, command: str, timeout: int) -> tuple[None, FakeStream, FakeStream]:
        del command, timeout
        return None, FakeStream('{"ok": true}'), FakeStream("")

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fake_paramiko(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeClient.instances = []
    FakeClient.outcomes = []
    monkeypatch.setattr(pi_device.paramiko, "SSHClient", FakeClient)


def run(password: str = "pw", private_key: str = "") -> tuple[str | None, str | None, int | None]:
    return pi_device.exec_pi_command(
        "pi.invalid", 22, "claude", password, HOST_KEY, "true", private_key=private_key
    )


def test_a_usable_key_is_the_only_credential_offered() -> None:
    output, error, status = run(private_key=ed25519_pem())

    assert (output, error, status) == ('{"ok": true}', "", 0)
    assert len(FakeClient.instances) == 1
    kwargs = FakeClient.instances[0].connect_kwargs
    assert isinstance(kwargs["pkey"], paramiko.PKey)
    assert kwargs["password"] is None
    assert kwargs["allow_agent"] is False and kwargs["look_for_keys"] is False


def test_without_a_key_the_password_is_used_exactly_as_before() -> None:
    assert run(password="pw")[2] == 0

    kwargs = FakeClient.instances[0].connect_kwargs
    assert kwargs["password"] == "pw"
    assert kwargs["pkey"] is None


def test_a_rejected_key_falls_back_to_the_password_on_a_fresh_connection() -> None:
    FakeClient.outcomes = [paramiko.AuthenticationException("rejected")]

    assert run(password="pw", private_key=ed25519_pem())[2] == 0

    first, second = FakeClient.instances
    assert first.closed and isinstance(first.connect_kwargs["pkey"], paramiko.PKey)
    assert second.connect_kwargs["password"] == "pw" and second.connect_kwargs["pkey"] is None


def test_a_rejected_key_without_a_password_fails_without_a_second_attempt() -> None:
    FakeClient.outcomes = [paramiko.AuthenticationException("rejected")]

    output, error, status = run(password="", private_key=ed25519_pem())

    assert output is None and status is None and "rejected" in str(error)
    assert len(FakeClient.instances) == 1


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timed out"), paramiko.SSHException("Error reading SSH protocol banner")],
)
def test_network_failures_never_trigger_a_second_login_attempt(failure: BaseException) -> None:
    FakeClient.outcomes = [failure]

    output, _, status = run(password="pw", private_key=ed25519_pem())

    assert output is None and status is None
    assert len(FakeClient.instances) == 1


def test_an_unreadable_key_uses_the_password_without_a_key_attempt() -> None:
    assert run(password="pw", private_key="not a key")[2] == 0

    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].connect_kwargs["password"] == "pw"


def test_an_unreadable_key_without_a_password_fails_cleanly() -> None:
    output, error, status = run(password="", private_key="not a key")

    assert output is None and status is None and "supported unencrypted key" in str(error)
    assert FakeClient.instances == []


def test_openssh_ed25519_and_pem_ecdsa_and_rsa_keys_all_load() -> None:
    assert isinstance(pi_device.load_private_key(ed25519_pem()), paramiko.Ed25519Key)
    for generated in (paramiko.ECDSAKey.generate(), paramiko.RSAKey.generate(2048)):
        buffer = io.StringIO()
        generated.write_private_key(buffer)
        assert pi_device.load_private_key(buffer.getvalue()).get_name() == generated.get_name()


def test_config_accepts_a_key_without_a_password_and_hides_both_secrets() -> None:
    base = {"host": "203.0.113.10", "port": 6000, "username": "pi", "host_key_sha256": HOST_KEY}

    config = dsh_client.PiDeviceConfig.from_value({**base, "private_key": "PRIVATE-KEY-BODY"})

    assert config.password == "" and config.private_key == "PRIVATE-KEY-BODY"
    both = dsh_client.PiDeviceConfig.from_value(
        {**base, "password": "PASSWORD-VALUE", "private_key": "PRIVATE-KEY-BODY"}
    )
    assert "PASSWORD-VALUE" not in repr(both) and "PRIVATE-KEY-BODY" not in repr(both)
    with pytest.raises(ValueError, match="missing required SSH fields"):
        dsh_client.PiDeviceConfig.from_value(base)


def test_fetch_passes_the_key_to_the_ssh_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_exec(*args: object, **kwargs: object) -> tuple[str, str, int]:
        captured["args"], captured["kwargs"] = args, kwargs
        return '{"ok": true, "days": []}', "", 0

    monkeypatch.setattr(dsh_client, "exec_pi_command", fake_exec)
    config = dsh_client.PiDeviceConfig.from_value(
        {
            "host": "203.0.113.10",
            "port": 6000,
            "username": "pi",
            "password": "pw",
            "private_key": "KEY",
            "host_key_sha256": HOST_KEY,
        }
    )

    dsh_client.fetch_inspect_payload(config, days=5)

    assert captured["kwargs"] == {"private_key": "KEY"}
    assert "curl -sS --fail" in str(captured["args"][5])  # type: ignore[index]


def test_variable_sync_keeps_a_key_added_on_the_host() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    source = (ROOT / "scripts" / "sync_pi_device_ssh.py").read_text(encoding="utf-8")

    assert 'if existing.get("private_key") and not value.get("private_key"):' in source
    assert 'value["private_key"] = existing["private_key"]' in source
    assert 'assert value.get("password") or value.get("private_key")' in source
    assert "print(existing" not in source
