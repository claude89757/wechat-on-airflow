#!/usr/bin/env python3
"""Read-only, single-attempt public-page contract probe on the scrape host.

This does not log in to DSH, read other task artifacts, solve challenges, inspect
cookies, send notifications, or change the running scraper. Public API samples
are reduced to a bounded field/type summary before they leave this process.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ORIGIN = "https://bawtt.ydmap.cn"
TARGETS = {"indoor": "111317", "outdoor": "103224"}
API_NAMES = {
    "getSalesItemList", "getSportVenueConfig", "getVenueCalendarList", "getVenueOrderList"
}
PUBLIC_NUMBERS = {
    "code", "status", "saleStatus", "available", "bookable", "canBook", "isOpen",
    "isSale", "disabled", "expired", "price", "salesItemId", "venueId", "curDate",
    "startTime", "endTime", "total", "count", "isAvailable", "canSale", "isExpired",
}
PUBLIC_TEXT = {"startTimeText", "endTimeText", "className", "venueName", "salesItemName"}
FORBIDDEN = re.compile(r"token|secret|password|cookie|authorization|phone|mobile|email|user|customer|member|contact", re.I)


def field_summary(value: object, key: str = "", depth: int = 0) -> object:
    """Expose schema, not account/order contents or authentication values."""
    if FORBIDDEN.search(key):
        return {"type": "omitted"}
    if depth > 6:
        return {"type": type(value).__name__}
    if isinstance(value, dict):
        return {
            k: field_summary(v, k, depth + 1)
            for k, v in list(value.items())[:45]
            if isinstance(k, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,60}", k)
        }
    if isinstance(value, list):
        return {"type": "list", "length": len(value), "sample": [field_summary(v, key, depth + 1) for v in value[:3]]}
    if value is None:
        return {"type": "null"}
    if type(value) in (bool, int, float):
        return {"type": type(value).__name__, **({"value": value} if key in PUBLIC_NUMBERS else {})}
    if isinstance(value, str):
        if key in PUBLIC_NUMBERS and re.fullmatch(r"[0-9]{1,16}", value):
            return {"type": "str", "value": value}
        if key in PUBLIC_TEXT and len(value) <= 80 and not re.search(r"https?://|@|[A-Za-z0-9_-]{32}", value):
            return {"type": "str", "value": value}
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}", value):
            return {"type": "str", "value": value}
        return {"type": "str"}
    return {"type": "unsupported"}


def api_name(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "bawtt.ydmap.cn":
        return None
    match = re.fullmatch(r"/srv\d+/api/pub/sport/venue/([A-Za-z]+)", parsed.path)
    return match[1] if match and match[1] in API_NAMES else None


PAGE_JS = r"""(() => {
const text = document.body ? document.body.innerText : '';
const challenge = /Access Verification|slide to verify|验证码|人机验证|滑动验证|安全验证/i.test(text);
const rootEl = document.querySelector('#app');
const root = rootEl && rootEl.__vue__;
const seen = new Set();
function find(vm) {
  if (!vm || seen.has(vm)) return null;
  seen.add(vm);
  const o = vm.$options || {};
  if ((o.name || o._componentTag) === 'ScheduleTable') return vm;
  for (const c of vm.$children || []) { const v = find(c); if (v) return v; }
  return null;
}
const table = find(root);
const rows = table && Array.isArray(table.rows) ? table.rows : [];
const parent = table && table.$parent;
return {
  source: location.href,
  challenge,
  appRoot: Boolean(rootEl),
  scripts: document.scripts.length,
  loading: /正在加载/.test(text),
  tableFound: Boolean(table),
  rowCount: rows.length,
  cells: challenge ? [] : rows.slice(0, 2),
  parentFields: challenge ? {} : (parent && parent.$data || {}),
  tableFields: challenge ? {} : (table && table.$data || {})
};
})()"""


class CDP:
    def __init__(self, url: str) -> None:
        import websocket
        self.ws = websocket.create_connection(url, timeout=5, suppress_origin=True, http_no_proxy=["127.0.0.1", "localhost"])
        self.sequence = 0
        self.events: list[dict[str, Any]] = []

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.sequence += 1
        request_id = self.sequence
        self.ws.send(json.dumps({"id": request_id, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            frame = json.loads(self.ws.recv())
            if frame.get("id") == request_id:
                if "error" in frame:
                    raise RuntimeError("cdp_request_failed")
                return frame.get("result", {})
            if "method" in frame and len(self.events) < 4000:
                self.events.append(frame)
        raise TimeoutError("cdp_response_deadline")

    def close(self) -> None:
        self.ws.close()


def probe_target(cdp: CDP, target: str) -> dict[str, Any]:
    product = TARGETS[target]
    url = f"{ORIGIN}/booking/schedule/104036?salesItemId={product}"
    report: dict[str, Any] = {"target": target, "salesItemId": product, "bookabilityVerified": False, "api": []}
    cdp.events.clear()
    cdp.call("Page.navigate", {"url": url})
    tracked: dict[str, dict[str, Any]] = {}
    finished: set[str] = set()
    processed: set[str] = set()
    deadline = time.monotonic() + 40
    page: dict[str, Any] = {}
    while time.monotonic() < deadline:
        evaluated = cdp.call("Runtime.evaluate", {"expression": PAGE_JS, "returnByValue": True})
        value = evaluated.get("result", {}).get("value")
        if not isinstance(value, dict):
            report["reason"] = "page_evaluation_failed"
            return report
        page = value
        if page.get("challenge"):
            report.update(reason="access_verification_required", challenge=True)
            return report
        if page.get("source") == "about:blank":
            time.sleep(0.2)
            continue
        parsed = urlsplit(str(page.get("source", "")))
        if parsed.scheme != "https" or parsed.netloc != "bawtt.ydmap.cn" or parsed.path != "/booking/schedule/104036" or parse_qs(parsed.query).get("salesItemId") != [product]:
            report["reason"] = "source_mismatch"
            return report
        events, cdp.events = cdp.events, []
        for event in events:
            params = event.get("params", {})
            request_id = params.get("requestId")
            if event.get("method") == "Network.responseReceived":
                response = params.get("response", {})
                name = api_name(str(response.get("url", "")))
                if name:
                    tracked[request_id] = {"name": name, "path": urlsplit(response["url"]).path, "httpStatus": response.get("status"), "mimeType": response.get("mimeType")}
            elif event.get("method") == "Network.loadingFinished":
                finished.add(request_id)
        for request_id in (set(tracked) & finished) - processed:
            processed.add(request_id)
            item = tracked[request_id]
            try:
                response = cdp.call("Network.getResponseBody", {"requestId": request_id})
                body = response.get("body", "")
                if response.get("base64Encoded") or len(body) > 1000000:
                    item["json"] = False
                else:
                    try:
                        item["schema"] = field_summary(json.loads(body))
                        item["json"] = True
                    except ValueError:
                        item["json"] = False
                        item["accessChallenge"] = bool(re.search(r"aliyun_waf|Access Verification|验证码|人机验证", body, re.I))
            except Exception as error:
                item["errorClass"] = type(error).__name__
            report["api"].append(item)
            if item.get("accessChallenge"):
                report.update(reason="access_verification_required", challenge=True)
                return report
        names = {a["name"] for a in report["api"] if a.get("json")}
        if page.get("tableFound") and names == API_NAMES:
            break
        time.sleep(1)
    report.update(reason="public_contract_observed" if page.get("tableFound") else "schedule_not_ready", page={k: page.get(k) for k in ("appRoot", "scripts", "loading", "tableFound", "rowCount")}, componentSchema=field_summary({k: page.get(k) for k in ("cells", "parentFields", "tableFields")}))
    return report


def main() -> dict[str, Any]:
    result: dict[str, Any] = {"mode": "single_attempt_public_browser_contract", "productionChanged": False, "externalTestSends": 0, "productionReady": False, "targets": []}
    binary = shutil.which("chromium") or shutil.which("chromium-browser")
    if binary is None:
        result["reason"] = "chromium_missing"
        return result
    process = None
    cdp = None
    with tempfile.TemporaryDirectory(prefix="bawtt-public-contract-") as profile:
        try:
            env = os.environ.copy()
            env.setdefault("DISPLAY", ":0")
            process = subprocess.Popen([binary, f"--user-data-dir={profile}", "--remote-debugging-port=0", "--no-first-run", "--no-default-browser-check", "about:blank"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            marker = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 15
            while not marker.is_file():
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError("browser_start_failed")
                time.sleep(0.2)
            port = int(marker.read_text().splitlines()[0])
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                pages = json.load(response)
            ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p.get("type") == "page")
            cdp = CDP(ws_url)
            cdp.call("Network.enable")
            cdp.call("Page.enable")
            for target in TARGETS:
                observation = probe_target(cdp, target)
                result["targets"].append(observation)
                if observation.get("challenge"):
                    result["reason"] = "stopped_on_access_verification"
                    break
        except Exception as error:
            result["reason"] = "public_probe_failed"
            result["errorClass"] = type(error).__name__
        finally:
            if cdp:
                try:
                    cdp.close()
                except Exception:
                    pass
            if process and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
    return result


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, sort_keys=True))
