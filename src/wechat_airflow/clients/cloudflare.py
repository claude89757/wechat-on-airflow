"""Bounded Cloudflare SSH pipe; authentication and host-key checks remain in SSHClient."""

from __future__ import annotations

import os
import re
import select
import subprocess
import threading
from collections.abc import Buffer, Mapping

import paramiko

_HOST = re.compile(
    r"(?=.{1,253}\Z)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}\Z"
)


def proxy_argv(hostname: str) -> list[str]:
    """Never accept shell fragments, URLs, flags, or arbitrary proxy programs."""
    if not isinstance(hostname, str) or not _HOST.fullmatch(hostname):
        raise ValueError("Cloudflare SSH requires a DNS hostname")
    return ["cloudflared", "access", "ssh", "--hostname", hostname, "--loglevel", "error"]


class CloudflareProxy(paramiko.ProxyCommand):
    """A socket-like pipe with EOF handling and idempotent child cleanup.

    Paramiko 3.5's ProxyCommand neither handles EOF nor reaps its process on
    close. These methods implement the public socket interface without a shell,
    process-global credential mutation, or credential-bearing command arguments.
    """

    def __init__(self, hostname: str, *, environment: Mapping[str, str] | None = None) -> None:
        self.cmd = proxy_argv(hostname)
        child_env = dict(os.environ if environment is None else environment)
        token_id = child_env.get("TUNNEL_SERVICE_TOKEN_ID", "")
        token_secret = child_env.get("TUNNEL_SERVICE_TOKEN_SECRET", "")
        if bool(token_id) != bool(token_secret):
            raise ValueError("Cloudflare Access service credentials must be supplied together")
        self._close_lock = threading.Lock()
        self.timeout: float | None = 15.0
        self.process = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            env=child_env,
        )

    def send(self, content: Buffer) -> int:
        stream = self.process.stdin
        if stream is None or stream.closed or self.closed:
            raise OSError("Cloudflare SSH pipe is closed")
        _, ready, _ = select.select([], [stream], [], self.timeout)
        if not ready:
            raise TimeoutError("Cloudflare SSH write timed out")
        return os.write(stream.fileno(), content)

    def recv(self, size: int) -> bytes:
        stream = self.process.stdout
        if size <= 0 or stream is None or stream.closed:
            return b""
        ready, _, _ = select.select([stream], [], [], self.timeout)
        if not ready:
            raise TimeoutError("Cloudflare SSH read timed out")
        return os.read(stream.fileno(), size)

    def close(self) -> None:
        with self._close_lock:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            for stream in (self.process.stdin, self.process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()

    @property
    def closed(self) -> bool:
        return self.process.poll() is not None


def ssh_proxy(hostname: str, transport: str) -> CloudflareProxy | None:
    if transport == "direct":
        return None
    if transport != "cloudflare":
        raise ValueError("SSH transport must be direct or cloudflare")
    return CloudflareProxy(hostname)
