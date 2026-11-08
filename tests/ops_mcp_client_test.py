from __future__ import annotations

import json
import stat
import sys
import threading
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ops_mcp  # noqa: E402

RESOURCE = ops_mcp.ENDPOINTS["pi"]
AUTH = {
    "authorization_endpoint": "https://access.example/authorize",
    "token_endpoint": "https://access.example/token",
    "registration_endpoint": "https://access.example/register",
}


class FakeServer:
    """Answers OAuth discovery, registration, token and MCP calls without a network."""

    def __init__(self, valid_tokens: set[str]) -> None:
        self.valid_tokens = valid_tokens
        self.calls: list[tuple[str, str]] = []
        self.issued = 0

    def __call__(
        self,
        method: str,
        url: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 60,
    ) -> tuple[int, dict[str, str], bytes]:
        del timeout
        self.calls.append((method, url))
        if url.endswith("/.well-known/oauth-protected-resource/mcp"):
            return (
                200,
                {},
                json.dumps({"authorization_servers": ["https://access.example"]}).encode(),
            )
        if url.endswith("/.well-known/oauth-authorization-server"):
            return 200, {}, json.dumps(AUTH).encode()
        if url == AUTH["registration_endpoint"]:
            return 201, {}, json.dumps({"client_id": "client-1"}).encode()
        if url == AUTH["token_endpoint"]:
            form = urllib.parse.parse_qs((body or b"").decode())
            if form["grant_type"] == ["refresh_token"] and form["refresh_token"] != ["refresh-ok"]:
                return 400, {}, b'{"error":"invalid_grant"}'
            self.issued += 1
            token = f"access-{self.issued}"
            self.valid_tokens.add(token)
            return (
                200,
                {},
                json.dumps({"access_token": token, "refresh_token": "refresh-ok"}).encode(),
            )
        if url == RESOURCE:
            bearer = (headers or {}).get("Authorization", "").removeprefix("Bearer ")
            if bearer not in self.valid_tokens:
                return 401, {}, b""
            request = json.loads(body or b"{}")
            if request.get("method") == "tools/list":
                payload = {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "result": {"tools": [{"name": "ops_status"}]},
                }
                event = "event: message\ndata: " + json.dumps(payload) + "\n\n"
                return 200, {"Content-Type": "text/event-stream"}, event.encode()
            return (
                200,
                {"Content-Type": "application/json", "Mcp-Session-Id": "s1"},
                b'{"jsonrpc":"2.0","result":{}}',
            )
        raise AssertionError(f"unexpected request {method} {url}")


def browser_with_session(opened: list[str]) -> Any:
    """Acts like a browser that already holds an Access session: it follows the redirect at once."""

    def open_url(url: str) -> bool:
        opened.append(url)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        callback = (
            query["redirect_uri"][0]
            + "?"
            + urllib.parse.urlencode({"code": "auth-code", "state": query["state"][0]})
        )
        threading.Thread(target=lambda: urllib.request.urlopen(callback, timeout=5).read()).start()
        return True

    return open_url


@pytest.fixture(autouse=True)
def token_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv(ops_mcp.TOKEN_DIR_ENV, str(tmp_path / "tokens"))
    return tmp_path / "tokens"


def test_sign_in_completes_through_a_signed_in_browser_and_stores_a_private_token(
    token_home: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    server, opened = FakeServer(set()), []

    session = ops_mcp.connect("pi", http=server, open_browser=browser_with_session(opened))

    assert session.tools() == ["ops_status"]
    url = urllib.parse.parse_qs(urllib.parse.urlsplit(opened[0]).query)
    assert url["code_challenge_method"] == ["S256"] and url["resource"] == [RESOURCE]
    assert url["redirect_uri"][0].startswith("http://localhost:")
    path = token_home / "pi.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(token_home.stat().st_mode) == 0o700
    assert json.loads(path.read_text())["access_token"] == "access-1"
    printed = capsys.readouterr()
    assert "access-1" not in printed.out + printed.err
    assert "refresh-ok" not in printed.out + printed.err


def test_a_valid_stored_token_needs_no_browser() -> None:
    ops_mcp.save_token("pi", {"resource": RESOURCE, "access_token": "kept"})
    opened: list[str] = []

    ops_mcp.connect("pi", http=FakeServer({"kept"}), open_browser=opened.append)

    assert opened == []


def test_a_rejected_token_is_refreshed_before_any_browser_sign_in() -> None:
    ops_mcp.save_token(
        "pi",
        {
            "resource": RESOURCE,
            "access_token": "expired",
            "refresh_token": "refresh-ok",
            "token_endpoint": AUTH["token_endpoint"],
            "client_id": "client-1",
        },
    )
    opened: list[str] = []

    ops_mcp.connect("pi", http=FakeServer(set()), open_browser=opened.append)

    assert opened == []
    assert ops_mcp.load_token("pi")["access_token"] == "access-1"  # type: ignore[index]


def test_a_failed_refresh_falls_back_to_the_browser_sign_in() -> None:
    ops_mcp.save_token(
        "pi",
        {
            "resource": RESOURCE,
            "access_token": "expired",
            "refresh_token": "revoked",
            "token_endpoint": AUTH["token_endpoint"],
            "client_id": "client-1",
        },
    )
    opened: list[str] = []

    ops_mcp.connect("pi", http=FakeServer(set()), open_browser=browser_with_session(opened))

    assert len(opened) == 1


def test_a_callback_with_the_wrong_state_is_refused() -> None:
    def forged_browser(url: str) -> bool:
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        callback = query["redirect_uri"][0] + "?code=stolen&state=wrong"
        threading.Thread(target=lambda: urllib.request.urlopen(callback, timeout=5).read()).start()
        return True

    with pytest.raises(ops_mcp.OpsMcpError, match="sign-in failed"):
        ops_mcp.sign_in(RESOURCE, http=FakeServer(set()), open_browser=forged_browser, timeout=5)
