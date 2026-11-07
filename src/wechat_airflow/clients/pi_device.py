from __future__ import annotations

import io
import logging

import paramiko

from wechat_airflow.clients.android_device import PinnedSHA256HostKeyPolicy

LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 180
SUPPORTED_KEY_TYPES = (paramiko.Ed25519Key, paramiko.ECDSAKey, paramiko.RSAKey)


def load_private_key(pem: str) -> paramiko.PKey:
    """Parse an unencrypted OpenSSH/PEM private key without writing it to disk."""
    last_error: Exception | None = None
    for key_type in SUPPORTED_KEY_TYPES:
        try:
            return key_type.from_private_key(io.StringIO(pem.strip() + "\n"))
        except (paramiko.SSHException, ValueError) as exc:
            last_error = exc
    raise paramiko.SSHException("private key is not a supported unencrypted key") from last_error


def _open_client(
    host: str,
    port: int,
    username: str,
    host_key_sha256: str,
    timeout_seconds: int,
    *,
    password: str | None = None,
    pkey: paramiko.PKey | None = None,
) -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    try:
        ssh.set_missing_host_key_policy(PinnedSHA256HostKeyPolicy(host_key_sha256))
        ssh.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            pkey=pkey,
            allow_agent=False,
            look_for_keys=False,
            timeout=timeout_seconds,
            auth_timeout=min(timeout_seconds, 30),
            banner_timeout=min(timeout_seconds, 30),
            disabled_algorithms={"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
        )
    except BaseException:
        ssh.close()
        raise
    return ssh


def _authenticated_client(
    host: str,
    port: int,
    username: str,
    password: str,
    host_key_sha256: str,
    private_key: str,
    timeout_seconds: int,
) -> tuple[paramiko.SSHClient, str]:
    """Prefer the key; use the password only if the key is unusable or rejected.

    Only an unusable key or an authentication rejection falls back. A network or
    host-key failure is returned as is, so a throttled sshd never sees a second
    connection attempt from the same call.
    """
    pkey: paramiko.PKey | None = None
    if private_key.strip():
        try:
            pkey = load_private_key(private_key)
        except paramiko.SSHException:
            if not password:
                raise
            LOGGER.warning("pi_host_ssh_key_unusable fallback=password")
    if pkey is not None:
        try:
            ssh = _open_client(host, port, username, host_key_sha256, timeout_seconds, pkey=pkey)
            return ssh, "publickey"
        except paramiko.AuthenticationException:
            if not password:
                raise
            LOGGER.warning("pi_host_ssh_key_rejected fallback=password")
    ssh = _open_client(host, port, username, host_key_sha256, timeout_seconds, password=password)
    return ssh, "password"


def exec_pi_command(
    host: str,
    port: int,
    username: str,
    password: str,
    host_key_sha256: str,
    cmd: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    private_key: str = "",
) -> tuple[str | None, str | None, int | None]:
    """Run one bounded command on the Raspberry Pi scrape host."""
    ssh: paramiko.SSHClient | None = None
    try:
        ssh, method = _authenticated_client(
            host,
            port,
            username,
            password,
            host_key_sha256,
            private_key,
            timeout_seconds,
        )
        LOGGER.info("pi_host_ssh_authenticated method=%s", method)
        _, stdout, stderr = ssh.exec_command(cmd, timeout=timeout_seconds)
        exit_status = stdout.channel.recv_exit_status()
        output = stdout.read().decode(errors="replace")
        error = stderr.read().decode(errors="replace")
        if exit_status != 0 and not error:
            error = f"command exited with status {exit_status}"
        return output, error, exit_status
    except Exception as exc:
        LOGGER.exception("pi_host_ssh_failed host=%s port=%s", host, port)
        return None, str(exc), None
    finally:
        if ssh is not None:
            ssh.close()
