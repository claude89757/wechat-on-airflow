"""Sender HTTP transport. Never retry a request whose submission is uncertain."""

from __future__ import annotations

import http.client
import json as json_module
from typing import Any
from urllib.parse import urlsplit

import paramiko
import requests

from wechat_airflow.clients.android_device import PinnedSHA256HostKeyPolicy
from wechat_airflow.clients.cloudflare import CloudflareProxy, proxy_argv

from .settings import _first_value

MAX_RESPONSE_BYTES = 1024 * 1024
ALLOWED_PATHS = {"/readyz", "/healthz", "/v1/wechat/send", "/v1/wechat/status"}


def validate_endpoint(endpoint: str) -> tuple[int, str]:
    parsed = urlsplit(endpoint)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.port != 7001
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ALLOWED_PATHS
    ):
        raise ValueError("SSH sender requires its declared loopback origin and API path")
    return parsed.port, parsed.path


def ssh_request(
    method: str,
    endpoint: str,
    *,
    identity: dict[str, Any],
    payload: dict[str, Any] | None,
    timeout: float,
) -> requests.Response:
    port, path = validate_endpoint(endpoint)
    if method not in {"GET", "POST"} or not 0 < timeout <= 210:
        raise ValueError("invalid bounded sender request")
    if identity.get("transport") != "cloudflare" or identity.get("port") != 22:
        raise ValueError("sender SSH identity has not been migrated")
    required = ("host", "username", "password", "host_key_sha256")
    if any(not isinstance(identity.get(key), str) or not identity[key] for key in required):
        raise ValueError("sender SSH identity is incomplete")
    proxy_argv(identity["host"])
    policy = PinnedSHA256HostKeyPolicy(identity["host_key_sha256"])
    body = None if payload is None else json_module.dumps(payload, ensure_ascii=False).encode()
    proxy = CloudflareProxy(identity["host"])
    client = paramiko.SSHClient()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    channel = None
    request_started = False
    try:
        client.set_missing_host_key_policy(policy)
        client.connect(
            hostname=identity["host"],
            port=22,
            username=identity["username"],
            password=identity["password"],
            sock=proxy,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
            allow_agent=False,
            look_for_keys=False,
            disabled_algorithms={"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
        )
        transport = client.get_transport()
        if transport is None or not transport.is_authenticated():
            raise RuntimeError("sender SSH is not authenticated")
        transport.set_keepalive(15)
        channel = transport.open_channel(
            "direct-tcpip", ("127.0.0.1", port), ("127.0.0.1", 0), timeout=15
        )
        channel.settimeout(timeout)
        connection.sock = channel
        request_started = True
        connection.request(
            method,
            path,
            body=body,
            headers={"Content-Type": "application/json", "Connection": "close"},
        )
        raw = connection.getresponse()
        data = raw.read(MAX_RESPONSE_BYTES + 1)
        if len(data) > MAX_RESPONSE_BYTES:
            raise ValueError("sender response exceeds size limit")
        response = requests.Response()
        response.status_code = raw.status
        response.headers.update(dict(raw.getheaders()))
        response._content = data
        response.encoding = "utf-8"
        response.url = endpoint
        return response
    except (OSError, paramiko.SSHException) as exc:
        if not request_started:
            raise requests.ConnectTimeout("sender tunnel failed before HTTP submission") from None
        raise requests.ConnectionError(
            "sender transport outcome requires ledger reconciliation"
        ) from exc
    finally:
        try:
            connection.close()
            if channel is not None:
                channel.close()
        finally:
            try:
                client.close()
            finally:
                proxy.close()


def sender_request(
    method: str,
    endpoint: str,
    *,
    json: dict[str, Any] | None = None,
    timeout: float,
) -> requests.Response:
    mode = _first_value("WECHAT_SEND_TRANSPORT") or "direct"
    if mode == "direct":
        if method == "GET":
            return requests.get(endpoint, timeout=timeout, allow_redirects=False)
        if method == "POST":
            return requests.post(endpoint, json=json, timeout=timeout, allow_redirects=False)
        raise ValueError("unsupported sender method")
    if mode != "cloudflare_ssh":
        raise ValueError("unsupported sender transport")
    identity = json_module.loads(_first_value("PI_DEVICE_SSH") or "null")
    if not isinstance(identity, dict):
        raise ValueError("sender SSH configuration is missing")
    return ssh_request(method, endpoint, identity=identity, payload=json, timeout=timeout)
