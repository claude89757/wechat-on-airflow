#!/usr/bin/env python3
"""Agent-side client for the operations MCP servers (Streamable HTTP + Cloudflare Access OAuth).

Sign-in needs no human step when the workstation's browser already holds a
Cloudflare Access session: the authorization page opens in that browser, Access
redirects straight back to a one-shot listener on localhost, and the code is
exchanged with PKCE. Only a browser without a session shows the Cloudflare login
page, and the person signs in there once.

Tokens are kept per endpoint in a 0600 file outside the repository, reused while
valid, refreshed when rejected, and never printed.

    python scripts/ops_mcp.py login pi
    python scripts/ops_mcp.py tools vps
    python scripts/ops_mcp.py call pi ops_status '{}'
    python scripts/ops_mcp.py exec vps --reason "read-only check" check.sh
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

ENDPOINTS = {
    "pi": "https://pi-mcp.zacks.vision/mcp",
    "vps": "https://vps-mcp.zacks.vision/mcp",
    "phone": "https://appium-mcp.zacks.vision/mcp",
}
TOKEN_DIR_ENV = "ZACKS_OPS_MCP_TOKEN_DIR"
DEFAULT_TOKEN_DIR = Path.home() / ".config" / "zacks-ops-mcp"
SIGN_IN_TIMEOUT_SECONDS = 600
# Cloudflare Access remembers the owner's consent per client name: a new name shows
# one "Authorize Client" page, a name already approved signs in with no click.
CLIENT_NAME_ENV = "ZACKS_OPS_MCP_CLIENT_NAME"
DEFAULT_CLIENT_NAME = "Claude Code desktop session"


class OpsMcpError(RuntimeError):
    pass


class Unauthorized(OpsMcpError):
    pass


Http = Callable[..., tuple[int, dict[str, str], bytes]]
Opener = Callable[[str], object]


def http_request(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers.items()), exc.read()


def _json(status: int, raw: bytes, what: str) -> dict[str, Any]:
    if status >= 400:
        raise OpsMcpError(f"{what} failed with HTTP {status}")
    value = json.loads(raw or b"{}")
    if not isinstance(value, dict):
        raise OpsMcpError(f"{what} returned a non-object")
    return value


def token_dir() -> Path:
    return Path(os.environ.get(TOKEN_DIR_ENV) or DEFAULT_TOKEN_DIR)


def token_path(name: str) -> Path:
    return token_dir() / f"{name}.json"


def load_token(name: str) -> dict[str, Any] | None:
    path = token_path(name)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) and value.get("access_token") else None


def save_token(name: str, token: dict[str, Any]) -> None:
    directory = token_dir()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = token_path(name)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(token, handle)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def discover(resource: str, http: Http = http_request) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(resource)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    metadata_url = f"{origin}/.well-known/oauth-protected-resource{parsed.path}"
    status, _, raw = http("GET", metadata_url, timeout=20)
    servers = _json(status, raw, "resource metadata").get("authorization_servers") or []
    if not servers:
        raise OpsMcpError("resource metadata names no authorization server")
    status, _, raw = http(
        "GET", f"{str(servers[0]).rstrip('/')}/.well-known/oauth-authorization-server", timeout=20
    )
    return _json(status, raw, "authorization server metadata")


def authorization_url(
    auth: dict[str, Any], client_id: str, redirect: str, resource: str, state: str, verifier: str
) -> str:
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect,
        "state": state,
        "code_challenge": challenge.decode(),
        "code_challenge_method": "S256",
        "resource": resource,
    }
    if auth.get("scopes_supported"):
        params["scope"] = " ".join(auth["scopes_supported"])
    return str(auth["authorization_endpoint"]) + "?" + urllib.parse.urlencode(params)


class _Callback:
    def __init__(self, state: str) -> None:
        self.state = state
        self.code: str | None = None
        self.error: str | None = None
        self.done = threading.Event()

    def handler(self) -> type[BaseHTTPRequestHandler]:
        callback = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                url = urllib.parse.urlsplit(self.path)
                if url.path != "/callback":
                    self.send_response(404)
                    self.end_headers()
                    return
                query = urllib.parse.parse_qs(url.query)
                if query.get("state", [""])[0] == callback.state and query.get("code"):
                    callback.code = query["code"][0]
                    message = "登录完成，可以关闭这个页面。"
                else:
                    callback.error = query.get("error", ["bad_callback"])[0][:80]
                    message = "登录失败。"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(message.encode())
                callback.done.set()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                del format, args

        return Handler


def sign_in(
    resource: str,
    *,
    http: Http = http_request,
    open_browser: Opener = webbrowser.open,
    timeout: float = SIGN_IN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    auth = discover(resource, http)
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    callback = _Callback(state)
    server = HTTPServer(("127.0.0.1", 0), callback.handler())
    redirect = f"http://localhost:{server.server_port}/callback"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, raw = http(
            "POST",
            str(auth["registration_endpoint"]),
            body=json.dumps(
                {
                    "client_name": os.environ.get(CLIENT_NAME_ENV) or DEFAULT_CLIENT_NAME,
                    "redirect_uris": [redirect],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "token_endpoint_auth_method": "none",
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            timeout=20,
        )
        client = _json(status, raw, "client registration")
        url = authorization_url(auth, str(client["client_id"]), redirect, resource, state, verifier)
        print(
            "opening the Cloudflare Access sign-in in this workstation's browser", file=sys.stderr
        )
        open_browser(url)
        if not callback.done.wait(timeout):
            raise OpsMcpError("timed out waiting for the browser sign-in")
    finally:
        server.shutdown()
        server.server_close()
    if callback.code is None:
        raise OpsMcpError(f"sign-in failed: {callback.error}")
    form = {
        "grant_type": "authorization_code",
        "code": callback.code,
        "redirect_uri": redirect,
        "client_id": str(client["client_id"]),
        "code_verifier": verifier,
        "resource": resource,
    }
    if client.get("client_secret"):
        form["client_secret"] = str(client["client_secret"])
    return _token_from_response(
        http, str(auth["token_endpoint"]), form, resource, client, "token exchange"
    )


def _token_from_response(
    http: Http,
    endpoint: str,
    form: dict[str, str],
    resource: str,
    client: dict[str, Any],
    what: str,
) -> dict[str, Any]:
    status, _, raw = http(
        "POST",
        endpoint,
        body=urllib.parse.urlencode(form).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    value = _json(status, raw, what)
    if not value.get("access_token"):
        raise OpsMcpError(f"{what} returned no access token")
    return {
        "resource": resource,
        "access_token": value["access_token"],
        "refresh_token": value.get("refresh_token") or form.get("refresh_token"),
        "token_endpoint": endpoint,
        "client_id": client.get("client_id"),
        "client_secret": client.get("client_secret"),
        "obtained_at": int(time.time()),
    }


def refresh(token: dict[str, Any], http: Http = http_request) -> dict[str, Any] | None:
    if not token.get("refresh_token") or not token.get("token_endpoint"):
        return None
    form = {
        "grant_type": "refresh_token",
        "refresh_token": str(token["refresh_token"]),
        "client_id": str(token.get("client_id") or ""),
        "resource": str(token["resource"]),
    }
    if token.get("client_secret"):
        form["client_secret"] = str(token["client_secret"])
    client = {"client_id": token.get("client_id"), "client_secret": token.get("client_secret")}
    try:
        return _token_from_response(
            http, str(token["token_endpoint"]), form, str(token["resource"]), client, "refresh"
        )
    except OpsMcpError:
        return None


def _parse_rpc(headers: dict[str, str], raw: bytes) -> dict[str, Any]:
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), "")
    text = raw.decode(errors="replace")
    if "text/event-stream" in content_type:
        rows = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        if not rows:
            raise OpsMcpError("event stream carried no data")
        text = rows[-1]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise OpsMcpError("MCP returned a non-object")
    return value


class Session:
    def __init__(self, resource: str, access_token: str, http: Http = http_request) -> None:
        self.resource = resource
        self.http = http
        self.headers = {
            "Authorization": "Bearer " + access_token,
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        self._next_id = 1
        status, headers, raw = self._post("initialize", self._initialize_params(), with_id=True)
        session_id = next((v for k, v in headers.items() if k.lower() == "mcp-session-id"), "")
        if session_id:
            self.headers["Mcp-Session-Id"] = session_id
        self._post("notifications/initialized", {}, with_id=False)

    @staticmethod
    def _initialize_params() -> dict[str, Any]:
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "zacks-ops-mcp", "version": "1"},
        }

    def _post(
        self, method: str, params: dict[str, Any], *, with_id: bool
    ) -> tuple[int, dict[str, str], bytes]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if with_id:
            body["id"] = self._next_id
            self._next_id += 1
        status, headers, raw = self.http(
            "POST", self.resource, body=json.dumps(body).encode(), headers=self.headers, timeout=600
        )
        if status in (401, 403):
            raise Unauthorized(f"{method}: HTTP {status}")
        if status >= 400:
            raise OpsMcpError(f"{method}: HTTP {status}")
        return status, headers, raw

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        _, headers, raw = self._post(method, params, with_id=True)
        value = _parse_rpc(headers, raw)
        if "error" in value:
            raise OpsMcpError(json.dumps(value["error"])[:500])
        result = value.get("result")
        return result if isinstance(result, dict) else {}

    def tools(self) -> list[str]:
        return [str(tool.get("name")) for tool in self.request("tools/list", {}).get("tools", [])]

    def call(self, tool: str, arguments: dict[str, Any]) -> str:
        result = self.request("tools/call", {"name": tool, "arguments": arguments})
        return "\n".join(
            str(item.get("text", ""))
            for item in result.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        )


def connect(
    name: str,
    *,
    http: Http = http_request,
    open_browser: Opener = webbrowser.open,
    sign_in_fn: Callable[..., dict[str, Any]] = sign_in,
) -> Session:
    """Reuse the stored token, refresh it, or sign in through the browser, in that order."""
    resource = ENDPOINTS.get(name, name)
    token = load_token(name)
    if token and token.get("resource") == resource:
        try:
            return Session(resource, str(token["access_token"]), http)
        except Unauthorized:
            renewed = refresh(token, http)
            if renewed:
                save_token(name, renewed)
                try:
                    return Session(resource, str(renewed["access_token"]), http)
                except Unauthorized:
                    pass
    fresh = sign_in_fn(resource, http=http, open_browser=open_browser)
    save_token(name, fresh)
    return Session(resource, str(fresh["access_token"]), http)


def _opener(browser: str | None) -> Opener:
    if not browser:
        return webbrowser.open
    return webbrowser.get(browser).open


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--browser", help="webbrowser name, for example 'chrome'")
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("login", "tools"):
        commands.add_parser(command).add_argument("endpoint")
    call = commands.add_parser("call")
    call.add_argument("endpoint")
    call.add_argument("tool")
    call.add_argument("arguments", nargs="?", default="{}")
    exec_parser = commands.add_parser("exec")
    exec_parser.add_argument("endpoint")
    exec_parser.add_argument("script", help="script file, or - for stdin")
    exec_parser.add_argument("--reason", required=True)
    exec_parser.add_argument("--timeout", type=int, default=120)
    exec_parser.add_argument("--wait", type=int, default=85)
    args = parser.parse_args(argv)

    try:
        session = connect(args.endpoint, open_browser=_opener(args.browser))
        if args.command == "login":
            print(f"signed in to {session.resource}")
        elif args.command == "tools":
            print(json.dumps(session.tools()))
        elif args.command == "call":
            print(session.call(args.tool, json.loads(args.arguments)))
        else:
            script = sys.stdin.read() if args.script == "-" else Path(args.script).read_text()
            text = session.call(
                "ops_exec",
                {
                    "command": script,
                    "reason": args.reason,
                    "timeoutSeconds": args.timeout,
                    "waitSeconds": args.wait,
                },
            )
            value = json.loads(text)
            result = value.get("result") or {}
            print("state:", value.get("state"), "exit:", result.get("exitCode"))
            print("request:", value.get("requestId"))
            print(result.get("output", ""))
            if result.get("stderr"):
                print("--- stderr ---")
                print(result["stderr"])
    except OpsMcpError as exc:
        print(f"ops-mcp: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
