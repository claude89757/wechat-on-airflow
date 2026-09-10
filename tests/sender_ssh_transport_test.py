from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from wechat_airflow.host_core import sender_transport as transport

URL = "http://127.0.0.1:7001/v1/wechat/send"


def identity():
    return {
        "host": "ssh.device.example",
        "port": 22,
        "transport": "cloudflare",
        "username": "test-user",
        "password": "test-only",
        "host_key_sha256": "SHA256:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1:7001/readyz",
        "http://remote.example:7001/readyz",
        "http://127.0.0.1:22/readyz",
        "http://u:p@127.0.0.1:7001/readyz",
        "http://127.0.0.1:7001/other",
        "http://127.0.0.1:7001/readyz?x=1",
    ],
)
def test_sender_tunnel_is_not_an_arbitrary_tcp_proxy(url):
    with pytest.raises(ValueError):
        transport.validate_endpoint(url)


def test_no_direct_fallback_after_tunnel_failure(monkeypatch):
    values = {"WECHAT_SEND_TRANSPORT": "cloudflare_ssh", "PI_DEVICE_SSH": json.dumps(identity())}
    monkeypatch.setattr(transport, "_first_value", lambda key: values.get(key))
    failed = MagicMock(side_effect=OSError("unavailable"))
    monkeypatch.setattr(transport, "ssh_request", failed)
    direct = MagicMock()
    monkeypatch.setattr(transport.requests, "post", direct)
    with pytest.raises(OSError):
        transport.sender_request("POST", URL, json={}, timeout=210)
    direct.assert_not_called()
    failed.assert_called_once()


def test_direct_transport_does_not_follow_redirects(monkeypatch):
    monkeypatch.setattr(transport, "_first_value", lambda key: None)
    post = MagicMock()
    monkeypatch.setattr(transport.requests, "post", post)
    transport.sender_request("POST", URL, json={"test": True}, timeout=10)
    post.assert_called_once_with(URL, json={"test": True}, timeout=10, allow_redirects=False)


def test_unknown_transport_is_rejected(monkeypatch):
    monkeypatch.setattr(transport, "_first_value", lambda key: "invalid")
    with pytest.raises(ValueError):
        transport.sender_request("GET", URL, timeout=10)


def test_payload_preserved_and_partial_write_never_replayed(monkeypatch):
    proxy, ssh, http = MagicMock(), MagicMock(), MagicMock()
    raw = http.getresponse.return_value
    raw.status = 200
    raw.getheaders.return_value = [("Content-Type", "application/json")]
    raw.read.return_value = b'{"success":true,"sent_count":1}'
    monkeypatch.setattr(transport, "CloudflareProxy", lambda host: proxy)
    monkeypatch.setattr(transport.paramiko, "SSHClient", lambda: ssh)
    monkeypatch.setattr(transport.http.client, "HTTPConnection", lambda *a, **k: http)
    payload = {"idempotency_key": "stable-test-only", "messages": ["test-only"]}
    result = transport.ssh_request("POST", URL, identity=identity(), payload=payload, timeout=210)
    assert result.json()["sent_count"] == 1
    assert ssh.connect.call_args.kwargs["sock"] is proxy
    assert ssh.connect.call_args.kwargs["look_for_keys"] is False
    assert json.loads(http.request.call_args.kwargs["body"]) == payload
    assert http.request.call_args.args == ("POST", "/v1/wechat/send")
    http.request.assert_called_once()
    http.close.assert_called_once()
    ssh.close.assert_called_once()
    proxy.close.assert_called_once()
    http.reset_mock()
    http.request.side_effect = OSError("partial write")
    with pytest.raises(transport.requests.ConnectionError) as ambiguous:
        transport.ssh_request("POST", URL, identity=identity(), payload=payload, timeout=210)
    assert not isinstance(ambiguous.value, transport.requests.ConnectTimeout)
    assert http.request.call_count == 1
    http.reset_mock()
    ssh.connect.side_effect = TimeoutError("not connected")
    with pytest.raises(transport.requests.ConnectTimeout):
        transport.ssh_request("POST", URL, identity=identity(), payload=payload, timeout=210)
    http.request.assert_not_called()


def test_invalid_identity_never_starts_a_proxy(monkeypatch):
    start = MagicMock()
    monkeypatch.setattr(transport, "CloudflareProxy", start)
    wrong = identity()
    wrong["host_key_sha256"] = "not-a-pin"
    with pytest.raises(ValueError):
        transport.ssh_request(
            "GET",
            URL.replace("/v1/wechat/send", "/readyz"),
            identity=wrong,
            payload=None,
            timeout=20,
        )
    start.assert_not_called()
