from __future__ import annotations

import logging

import paramiko

from wechat_airflow.clients.android_device import PinnedSHA256HostKeyPolicy

LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 180


def exec_pi_command(
    host: str,
    port: int,
    username: str,
    password: str,
    host_key_sha256: str,
    cmd: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[str | None, str | None, int | None]:
    """Run one bounded command on the Raspberry Pi scrape host."""
    ssh: paramiko.SSHClient | None = None
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(PinnedSHA256HostKeyPolicy(host_key_sha256))
        ssh.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            allow_agent=False,
            look_for_keys=False,
            timeout=timeout_seconds,
            auth_timeout=min(timeout_seconds, 30),
            banner_timeout=min(timeout_seconds, 30),
            disabled_algorithms={"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
        )
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
