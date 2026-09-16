"""Passive, bounded public-query evidence; JSON decoding is never bookability."""

from __future__ import annotations

import base64
import json
import re
from typing import Any
from urllib.parse import urlsplit

from bawtt_live_query import shape

HOSTS = {"wxsports.ydmap.cn", "bawtt.ydmap.cn"}
QUERY = re.compile(
    r"/srv\d+/api/pub/(?:sport/venue/(?:getSalesItemList|getSportVenueConfig|"
    r"getVenueCalendarList|getVenueOrderList)|basic/getConfig)"
)


def public_text(value: object) -> str:
    text = str(value or "")[:2000]
    text = re.sub(r"https?://[^\s\"'<>]+", "[url]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(
        r"(?i)(token|password|cookie|authorization|secret|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=[omitted]",
        text,
    )
    text = re.sub(r"[A-Za-z0-9_+/=-]{24,}", "[opaque]", text)
    return re.sub(r"\b\d{11,}\b", "[number]", text)[:600]


def query_path(url: str, host: str) -> str | None:
    parsed = urlsplit(url)
    if host in HOSTS and parsed.scheme == "https" and parsed.netloc == host:
        return parsed.path if QUERY.fullmatch(parsed.path) else None
    return None


def summarize_body(status: object, mime: str, raw: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "httpStatus": status,
        "mime": mime[:80],
        "json": False,
        "bookabilityVerified": False,
        "businessSuccess": False,
    }
    if len(raw) > 500000:
        return {**result, "state": "oversized_response"}
    if re.search(r"aliyun_waf|Access Verification|人机验证|验证码|滑动验证", raw, re.I):
        return {**result, "state": "access_verification_required", "accessChallenge": True}
    try:
        value = json.loads(raw)
    except ValueError:
        title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
        return {
            **result,
            "state": "non_json_response",
            "htmlTitle": public_text(title.group(1)) if title else "",
        }
    result.update(json=True, shape=shape(value), state="json_observed_contract_unverified")
    if type(status) not in (int, float) or not 200 <= status < 300:
        return {**result, "state": "http_error"}
    if not isinstance(value, dict):
        return result
    # Retain observed envelope values; do not invent a vendor success-code convention.
    for key in ("code", "success", "status"):
        scalar = value.get(key)
        if scalar is None or type(scalar) in (bool, int, float):
            result[key] = scalar
        elif isinstance(scalar, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", scalar):
            result[key] = scalar
    for key in ("message", "msg", "error"):
        if isinstance(value.get(key), str):
            result[key] = public_text(value[key])
    if value.get("success") is False or value.get("ok") is False:
        result["state"] = "business_error"
    return result


class QueryTrace:
    """Receive only this page's events after normal startup, without replaying requests."""

    def __init__(self, url: str, host: str) -> None:
        import websocket

        self.ws = websocket.create_connection(url, timeout=5, suppress_origin=True)
        self.host = host
        self.next_id = 0
        self.pending: dict[str, dict[str, Any]] = {}
        self.body_requests: dict[int, dict[str, Any]] = {}
        self.results: list[dict[str, Any]] = []
        self.ws.send(json.dumps({"id": 0, "method": "Network.enable", "params": {}}))
        self.ws.settimeout(0.05)

    def drain(self) -> None:
        import websocket

        for _ in range(300):
            try:
                event = json.loads(self.ws.recv())
            except websocket.WebSocketTimeoutException:
                return
            if "id" in event:
                item = self.body_requests.pop(event["id"], None)
                if item is not None:
                    payload = event.get("result", {})
                    if "body" not in payload:
                        item["state"] = "response_body_unavailable"
                    else:
                        try:
                            raw = payload["body"]
                            if payload.get("base64Encoded"):
                                raw = base64.b64decode(raw, validate=True).decode("utf-8")
                            item.update(summarize_body(item["httpStatus"], item["mime"], raw))
                        except (ValueError, UnicodeError):
                            item["state"] = "invalid_response_encoding"
                    self.results.append(item)
                continue
            params = event.get("params", {})
            request_id = params.get("requestId")
            if event.get("method") == "Network.responseReceived":
                response = params.get("response", {})
                path = query_path(response.get("url", ""), self.host)
                if path and len(self.pending) + len(self.body_requests) + len(self.results) < 16:
                    self.pending[request_id] = {
                        "path": path,
                        "httpStatus": response.get("status"),
                        "mime": response.get("mimeType", ""),
                        "businessSuccess": False,
                    }
            elif event.get("method") == "Network.loadingFinished" and request_id in self.pending:
                item = self.pending.pop(request_id)
                self.next_id += 1
                self.body_requests[self.next_id] = item
                self.ws.send(
                    json.dumps(
                        {
                            "id": self.next_id,
                            "method": "Network.getResponseBody",
                            "params": {"requestId": request_id},
                        }
                    )
                )
            elif event.get("method") == "Network.loadingFailed" and request_id in self.pending:
                self.results.append({**self.pending.pop(request_id), "state": "loading_failed"})

    def close(self) -> None:
        self.ws.close()
