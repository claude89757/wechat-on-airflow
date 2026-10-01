"""Passive, bounded public-query evidence; JSON decoding is never bookability."""

from __future__ import annotations

import base64
import json
import math
import re
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bawtt_live_query import shape

HOSTS = {"wxsports.ydmap.cn", "bawtt.ydmap.cn"}
QUERY = re.compile(
    r"/srv\d+/api/pub/(?:sport/venue/(?:getSalesItemList|getSportVenueConfig|"
    r"getVenueCalendarList|getVenueOrderList)|basic/getConfig)"
)

CHALLENGE_TEXT = re.compile(
    r"aliyun_waf|waf-nc-mask|Access\s+Verification|slide\s+to\s+verify|"
    r"访问\s*验证|安全\s*验证|人机\s*验证|验证码|滑动\s*验证",
    re.I,
)
PAGE_ACCESS_JS = r"""
const text=document.body?.innerText||'';
const textPresent=/Access\s+Verification|slide\s+to\s+verify|访问\s*验证|安全\s*验证|人机\s*验证|验证码|滑动\s*验证/i.test(text);
function visible(el) {
  const r=el.getBoundingClientRect();
  if(r.width<=0 || r.height<=0 || r.right<=0 || r.bottom<=0 ||
     r.left>=innerWidth || r.top>=innerHeight) return false;
  for(let ancestor=el;ancestor;ancestor=ancestor.parentElement) {
    const s=getComputedStyle(ancestor);
    if(s.display==='none' || s.visibility==='hidden' || s.visibility==='collapse' ||
       Number(s.opacity)===0 || s.contentVisibility==='hidden') return false;
  }
  return true;
}
// This mask is outside the Vue component tree. Generic date Sliders are unrelated.
const maskVisible=[...document.querySelectorAll('.waf-nc-mask')].some(visible);
return {accessChallenge:textPresent||maskVisible,
        accessChallengeText:textPresent,wafMaskVisible:maskVisible};
"""


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
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
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
    if CHALLENGE_TEXT.search(raw):
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
            if CHALLENGE_TEXT.search(value[key]):
                return {**result, "state": "access_verification_required", "accessChallenge": True}
    if value.get("success") is False or value.get("ok") is False:
        result["state"] = "business_error"
    return result


def _number(value: object) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def request_metadata(request: dict[str, Any]) -> dict[str, Any]:
    """Only literal public IDs/dates already supplied by CDP, never headers/tokens.

    Do not fetch omitted POST data, decrypt opaque payloads, or infer a request's
    product from the current DOM. Ambiguous/duplicate values remain unknown.
    """
    allowed = ("salesId", "salesItemId", "date", "curDate", "bookDate", "bookingDate")
    values: dict[str, list[Any]] = {key: [] for key in allowed}
    ambiguous: set[str] = set()
    body_state = "absent"
    try:
        query = parse_qs(
            urlsplit(str(request.get("url", ""))).query, keep_blank_values=True, max_num_fields=64
        )
    except ValueError:
        query = {}
        ambiguous.update(allowed)
    for key in allowed:
        values[key].extend(query.get(key, []))
        if len(query.get(key, [])) > 1:
            ambiguous.add(key)
    raw = request.get("postData")
    if isinstance(raw, str) and len(raw) <= 16384:
        body_state = "opaque"
        try:
            if raw.lstrip().startswith("{"):
                # Preserve duplicate JSON keys so they cannot silently overwrite identity.
                pairs = json.loads(raw, object_pairs_hook=lambda pairs: pairs)
                if isinstance(pairs, list):
                    body_state = "json"
                    for key, value in pairs:
                        if key in values:
                            values[key].append(value)
                    keys = [key for key, _ in pairs]
                    ambiguous.update(key for key in allowed if keys.count(key) > 1)
            elif "=" in raw:
                body = parse_qs(raw, keep_blank_values=True, max_num_fields=64, strict_parsing=True)
                body_state = "form"
                for key in allowed:
                    values[key].extend(body.get(key, []))
                    if len(body.get(key, [])) > 1:
                        ambiguous.add(key)
        except (ValueError, TypeError, RecursionError):
            body_state = "unreadable"
            ambiguous.update(allowed)
    elif request.get("hasPostData") or raw is not None:
        body_state = "omitted_or_oversized"
    public: dict[str, str] = {}
    for key, candidates in values.items():
        normalized: list[str] = []
        for candidate in candidates:
            text = str(candidate) if type(candidate) in (int, str) else ""
            valid = (
                bool(re.fullmatch(r"[1-9][0-9]{0,8}", text))
                if key in ("salesId", "salesItemId")
                else False
            )
            if key not in ("salesId", "salesItemId") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                try:
                    date.fromisoformat(text)
                    valid = True
                except ValueError:
                    pass
            if not valid:
                ambiguous.add(key)
            normalized.append(text)
        if len(set(normalized)) > 1:
            ambiguous.add(key)
        if normalized and key not in ambiguous:
            public[key] = normalized[0]
    binding = (
        "ambiguous"
        if "salesItemId" in ambiguous
        else "observed"
        if "salesItemId" in public
        else "unknown"
    )
    return {
        "publicParameters": public,
        "productBinding": binding,
        "bodyEvidence": body_state,
        "ambiguousParameters": sorted(ambiguous),
    }


class QueryTrace:
    """Bounded late-attached observation. Does not navigate, replay or solve access checks."""

    def __init__(self, url: str, host: str) -> None:
        import websocket

        parsed = urlsplit(url)
        if (
            host not in HOSTS
            or parsed.scheme != "ws"
            or parsed.hostname not in ("127.0.0.1", "localhost")
            or parsed.username
            or parsed.password
        ):
            raise ValueError("invalid_local_trace_endpoint")
        self.ws = websocket.create_connection(
            url, timeout=5, suppress_origin=True, http_no_proxy=["127.0.0.1", "localhost"]
        )
        self.host = host
        self.next_id = 0
        self.pending: dict[str, dict[str, Any]] = {}
        self.body_requests: dict[int, dict[str, Any]] = {}
        self.results: list[dict[str, Any]] = []
        self.opened_at = datetime.now(UTC).isoformat()
        self.enabled = False
        self.queue_drained = False
        self.counts = dict.fromkeys(
            (
                "observedRequestStarts",
                "allowlistedRequestStarts",
                "retainedRequests",
                "droppedStartEvents",
                "droppedResponseEvents",
                "responsesWithoutStart",
                "redirects",
                "duplicateStartEvents",
                "invalidFrames",
                "drainLimitHits",
            ),
            0,
        )
        self.ws.send(json.dumps({"id": 0, "method": "Network.enable", "params": {}}))
        self.ws.settimeout(0.05)

    def coverage(self) -> dict[str, Any]:
        return {
            "openedAt": self.opened_at,
            "networkEnabled": self.enabled,
            "captureScope": "this_page_after_attachment_allowlisted_queries",
            "fullNavigationCaptured": False,
            "triggerRateEstimable": False,
            "queueDrained": self.queue_drained,
            **self.counts,
            "awaitingResponseOrFinish": len(self.pending),
            "awaitingBody": len(self.body_requests),
            "completedRecords": len(self.results),
        }

    def _new(self, request_id: str, path: str) -> dict[str, Any] | None:
        if self.counts["retainedRequests"] >= 16:
            return None
        self.counts["retainedRequests"] += 1
        item: dict[str, Any] = {
            "sampleNumber": self.counts["retainedRequests"],
            "path": path,
            "requestStartObserved": False,
            "startOrder": None,
            "startedAt": None,
            "requestTimestamp": None,
            "productBinding": "unknown",
            "publicParameters": {},
            "businessSuccess": False,
            "bookabilityVerified": False,
        }
        self.pending[request_id] = item
        return item

    def _finish(self, item: dict[str, Any], state: str | None = None) -> None:
        if state:
            item["state"] = state
        start, end = item.get("requestTimestamp"), item.get("finishedTimestamp")
        item["durationMs"] = (
            round((end - start) * 1000, 3)
            if start is not None and end is not None and end >= start
            else None
        )
        self.results.append(item)

    def consume(self, event: dict[str, Any]) -> None:
        """Process a CDP frame; public for deterministic, socket-free fixtures."""
        if "id" in event:
            if event["id"] == 0:
                self.enabled = "result" in event and "error" not in event
                if not self.enabled:
                    raise RuntimeError("network_observer_enable_failed")
                return
            item = self.body_requests.pop(event["id"], None)
            if item is None:
                return
            payload = event.get("result", {})
            raw = payload.get("body")
            if not isinstance(raw, str):
                self._finish(item, "response_body_unavailable")
                return
            try:
                if len(raw) > 700000:
                    self._finish(item, "oversized_response")
                    return
                if payload.get("base64Encoded"):
                    raw = base64.b64decode(raw, validate=True).decode("utf-8")
                item.update(summarize_body(item.get("httpStatus"), item.get("mime", ""), raw))
                self._finish(item)
            except (ValueError, UnicodeError):
                self._finish(item, "invalid_response_encoding")
            return
        params = event.get("params", {})
        request_id = params.get("requestId")
        if not isinstance(request_id, str):
            return
        method = event.get("method")
        if method == "Network.requestWillBeSent":
            self.counts["observedRequestStarts"] += 1
            old = self.pending.get(request_id)
            if "redirectResponse" in params:
                self.counts["redirects"] += 1
                if old is not None:
                    self.pending.pop(request_id)
                    old["finishedTimestamp"] = _number(params.get("timestamp"))
                    self._finish(old, "redirected")
            elif old is not None:
                self.counts["duplicateStartEvents"] += 1
                return
            request = params.get("request", {})
            path = query_path(request.get("url", ""), self.host)
            if path is None:
                return
            self.counts["allowlistedRequestStarts"] += 1
            item = self._new(request_id, path)
            if item is None:
                self.counts["droppedStartEvents"] += 1
                return
            item.update(request_metadata(request))
            item.update(
                requestStartObserved=True,
                startOrder=self.counts["allowlistedRequestStarts"],
                requestTimestamp=_number(params.get("timestamp")),
            )
            verb = request.get("method")
            item["method"] = verb if verb in ("GET", "POST", "OPTIONS", "HEAD") else "other"
            wall_time = _number(params.get("wallTime"))
            if wall_time is not None and 946684800 <= wall_time < 4102444800:
                item["startedAt"] = datetime.fromtimestamp(wall_time, UTC).isoformat()
        elif method == "Network.responseReceived":
            response = params.get("response", {})
            path = query_path(response.get("url", ""), self.host)
            item = self.pending.get(request_id)
            if path is None or (item is not None and item["path"] != path):
                if item is not None:
                    self.pending.pop(request_id)
                    self._finish(item, "response_source_mismatch")
                return
            if item is None:
                item = self._new(request_id, path)
                if item is None:
                    self.counts["droppedResponseEvents"] += 1
                    return
                self.counts["responsesWithoutStart"] += 1
            mime = response.get("mimeType", "")
            item.update(
                httpStatus=_number(response.get("status")),
                mime=mime[:80] if isinstance(mime, str) else "",
                responseTimestamp=_number(params.get("timestamp")),
            )
        elif (
            method in ("Network.loadingFinished", "Network.loadingFailed")
            and request_id in self.pending
        ):
            item = self.pending.pop(request_id)
            item["finishedTimestamp"] = _number(params.get("timestamp"))
            if method == "Network.loadingFailed":
                self._finish(item, "loading_failed")
            elif "httpStatus" not in item:
                self._finish(item, "response_event_missing")
            else:
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

    def drain(self) -> None:
        import websocket

        self.queue_drained = False
        for _ in range(300):
            try:
                raw = self.ws.recv()
            except websocket.WebSocketTimeoutException:
                self.queue_drained = True
                return
            if not raw:
                raise RuntimeError("network_observer_disconnected")
            try:
                if len(raw) > 1100000:
                    raise ValueError("oversized_frame")
                event = json.loads(raw)
                if not isinstance(event, dict):
                    raise ValueError("invalid_frame")
                self.consume(event)
            except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
                self.counts["invalidFrames"] += 1
        self.counts["drainLimitHits"] += 1

    def close(self) -> None:
        self.ws.close()
