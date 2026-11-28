"""Key-first login to the Raspberry Pi for the protected deployment scripts.

The protected ``production`` GitHub Environment may hold ``PI_DEVICE_SSH_PRIVATE_KEY``
(an unencrypted OpenSSH or PEM key) and, during migration, ``PI_DEVICE_SSH_PASSWORD``.
The key is tried first. The password is used only when the key is missing, unusable,
or explicitly rejected by the server, so a host that has switched off password login
keeps working and a host that has not yet authorised the key still works too.

Network and host-key failures are never retried with the password: a second attempt
would only add another connection to an sshd that is already throttling scanners.
Nothing here prints or logs credential values or raw exception text.
"""

from __future__ import annotations

import io
import os
from collections.abc import Mapping
from typing import Any

import paramiko

KEY_ENV = "PI_DEVICE_SSH_PRIVATE_KEY"
PASSWORD_ENV = "PI_DEVICE_SSH_PASSWORD"
KEY_TYPES = (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey)


def has_credentials(env: Mapping[str, str] | None = None) -> bool:
    """True when at least one of the key or the password is configured."""
    values = os.environ if env is None else env
    return bool(values.get(KEY_ENV, "").strip() or values.get(PASSWORD_ENV, ""))


def load_private_key(pem: str) -> paramiko.PKey:
    """Parse an unencrypted private key held only in memory."""
    for key_type in KEY_TYPES:
        try:
            return key_type.from_private_key(io.StringIO(pem.strip() + "\n"))
        except (paramiko.SSHException, ValueError):
            continue
    raise paramiko.SSHException("pi_ssh_key_unusable")


def connect_from_env(
    client: paramiko.SSHClient,
    hostname: str,
    port: int,
    username: str,
    *,
    env: Mapping[str, str] | None = None,
    **connect_options: Any,
) -> str:
    """Connect ``client`` with the key first; return ``"publickey"`` or ``"password"``.

    ``connect_options`` are passed through to ``SSHClient.connect`` (timeouts, a proxy
    ``sock`` and so on). The caller keeps ownership of the host-key policy.
    """
    values = os.environ if env is None else env
    pem = values.get(KEY_ENV, "").strip()
    password = values.get(PASSWORD_ENV, "")
    if not pem and not password:
        raise RuntimeError("pi_ssh_credentials_missing")
    options: dict[str, Any] = {"allow_agent": False, "look_for_keys": False, **connect_options}

    pkey: paramiko.PKey | None = None
    if pem:
        try:
            pkey = load_private_key(pem)
        except paramiko.SSHException:
            if not password:
                raise
    if pkey is not None:
        try:
            client.connect(hostname=hostname, port=port, username=username, pkey=pkey, **options)
            return "publickey"
        except paramiko.AuthenticationException:
            # A caller-supplied socket (a proxy channel) is spent after a rejected login,
            # so only a fresh TCP connection can be retried with the password.
            if not password or options.get("sock") is not None:
                raise
            client.close()
    client.connect(hostname=hostname, port=port, username=username, password=password, **options)
    return "password"
