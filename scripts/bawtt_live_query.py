#!/usr/bin/env python3
"""Observe public booking queries on the scrape host without publishing slots."""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

ORIGIN = "https://bawtt.ydmap.cn"
TARGETS = {"outdoor": "103224", "indoor": "111317"}
QUERIES = {
    "getSalesItemList",
    "getSportVenueConfig",
    "getVenueCalendarList",
    "getVenueOrderList",
}
PRIVATE = re.compile(r"user|member|customer|phone|mobile|email|token|secret|cookie|auth|sign", re.I)
SAFE_SCALARS = {
    "code",
    "success",
    "status",
    "state",
    "saleStatus",
    "orderStatus",
    "isOpen",
    "isAvailable",
    "available",
    "canBook",
    "bookable",
    "expired",
    "price",
    "venueId",
    "salesItemId",
    "date",
    "bookDate",
    "bookingDate",
    "startTime",
    "endTime",
    "startDate",
    "endDate",
    "venueName",
    "salesItemName",
    "platformName",
    "className",
}
PAGE_JS = r"""
const text = document.body ? document.body.innerText : '';
const root = document.querySelector('#app');
const seen = new Set();
function find(vm) {
  if (!vm || seen.has(vm)) return null;
  seen.add(vm);
  const o = vm.$options || {};
  if ((o.name || o._componentTag) === 'ScheduleTable') return vm;
  for (const c of vm.$children || []) { const t = find(c); if (t) return t; }
  return null;
}
const table = find(root && root.__vue__);
const fields = new Set(), classes = {}, courts = new Set(), sample = [];
let cells = 0;
for (const row of (table && table.rows || [])) {
  for (const col of (Array.isArray(row) ? row : Object.values(row || {}))) {
    if (!col || !col.startTimeText || !col.endTimeText) continue;
    cells++;
    Object.keys(col).forEach(k => fields.add(k));
    const cls = typeof col.className === 'string' ? col.className : '';
    if (/^[a-zA-Z0-9 _-]{0,100}$/.test(cls)) classes[cls] = (classes[cls] || 0) + 1;
    if (col.platformInfo && typeof col.platformInfo.venueName === 'string')
      courts.add(col.platformInfo.venueName.slice(0,60));
    if (sample.length < 3) {
      const cell = {startTimeText: col.startTimeText, endTimeText: col.endTimeText,
                    className: cls};
      for (const k of ['expired','status','state','available','bookable','price'])
        if (typeof col[k] === 'boolean' || typeof col[k] === 'number') cell[k] = col[k];
      sample.push(cell);
    }
  }
}
const dates = [...text.matchAll(/\b\d{2}-\d{2}\b/g)].map(m => m[0]);
return {
  challenge: /Access Verification|slide to verify|滑动.*验证|拼图.*验证|安全验证|人机验证/i.test(text),
  loginRequired: /请先登录|登录后查看|sign in to continue/i.test(text),
  loading: /正在加载/.test(text), notReleased: /暂未开放|尚未开放/.test(text),
  appRoot: Boolean(root), tableFound: Boolean(table), cells,
  fieldNames: [...fields].sort(), classCounts: classes, courtNames: [...courts], sample,
  dateLabels: [...new Set(dates)].slice(0,14), bodyTextLength: text.length,
  tablePropNames: table ? Object.keys(table.$props || {}).sort() : [],
  tableDataNames: table ? Object.keys(table.$data || {}).sort() : [],
  documentState: document.readyState,
  scriptCount: document.scripts.length,
  iframeCount: document.querySelectorAll('iframe').length,
  vuePresent: Boolean(root && root.__vue__),
  wasmAvailable: typeof WebAssembly !== 'undefined',
  publicText: text.slice(0, 1000)
};
"""


def public_text(value: object) -> str:
    """Bound ordinary unauthenticated-page diagnostics; exclude identifiers."""
    text = str(value or "")[:2000]
    text = re.sub(r"https?://[^\s\"'<>]+", "[url]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(
        r"(?i)(token|password|cookie|authorization|secret|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=[omitted]",
        text,
    )
    text = re.sub(r"[A-Za-z0-9_+/=-]{20,}", "[opaque]", text)
    text = re.sub(r"\b\d{11,}\b", "[number]", text)
    return text[:600]


def browser_diagnostics(driver: Any) -> list[dict[str, str]]:
    rows = []
    for entry in driver.get_log("browser"):
        if entry.get("level") in ("SEVERE", "WARNING"):
            rows.append({"level": entry["level"], "message": public_text(entry.get("message"))})
    return rows[:12]


def query_path(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "bawtt.ydmap.cn":
        return None
    match = re.fullmatch(r"/srv\d+/api/pub/sport/venue/([A-Za-z]+)", parsed.path)
    return parsed.path if match and match[1] in QUERIES else None


def source_matches(url: str, target: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.netloc == "bawtt.ydmap.cn"
        and parsed.path == "/booking/schedule/104036"
        and parse_qs(parsed.query).get("salesItemId") == [TARGETS[target]]
    )


def shape(value: Any, key: str = "", depth: int = 0) -> Any:
    """Keep schema and allowlisted public booking fields, never arbitrary values."""
    if depth > 7:
        return "depth_limit"
    if isinstance(value, dict):
        return {
            k: shape(v, k, depth + 1)
            for k, v in list(value.items())[:40]
            if isinstance(k, str) and k.isidentifier() and not PRIVATE.search(k)
        }
    if isinstance(value, list):
        return {"length": len(value), "items": [shape(v, key, depth + 1) for v in value[:2]]}
    if key in SAFE_SCALARS and (value is None or type(value) in (bool, int, float)):
        return value
    if key in SAFE_SCALARS and isinstance(value, str) and len(value) <= 60:
        if not re.search(r"https?://|@|\d{11,}", value):
            return value
    return type(value).__name__


def read_queries(
    driver: Any,
    pending: dict[str, str],
    results: list[dict[str, Any]],
    resources: list[dict[str, Any]],
) -> None:
    for entry in driver.get_log("performance"):
        message = json.loads(entry["message"])["message"]
        params = message.get("params", {})
        request_id = params.get("requestId")
        if message["method"] == "Network.responseReceived":
            response = params["response"]
            parsed = urlsplit(response["url"])
            if (
                (parsed.hostname == "ydmap.cn" or str(parsed.hostname).endswith(".ydmap.cn"))
                and params.get("type") in ("Document", "Script", "Fetch", "XHR")
                and len(resources) < 50
            ):
                resources.append(
                    {
                        "path": parsed.path,
                        "type": params.get("type"),
                        "status": response.get("status"),
                        "mime": response.get("mimeType"),
                    }
                )
            path = query_path(response["url"])
            if path:
                pending[request_id] = path
        if message["method"] != "Network.loadingFinished" or request_id not in pending:
            continue
        path = pending.pop(request_id)
        item: dict[str, Any] = {"path": path, "json": False}
        try:
            payload = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
            raw = payload["body"]
            if payload.get("base64Encoded"):
                raw = base64.b64decode(raw).decode("utf-8")
            if len(raw) > 500000:
                item["error"] = "oversized_query_response"
            else:
                try:
                    value = json.loads(raw)
                    item.update(json=True, shape=shape(value))
                except ValueError:
                    item["accessChallenge"] = bool(
                        re.search(r"aliyun_waf|Access Verification|验证码|人机验证", raw, re.I)
                    )
                    item["error"] = "non_json_query_response"
        except Exception as exc:
            item["errorClass"] = type(exc).__name__
        if len(results) < 12:
            results.append(item)


def observe(driver: Any, target: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "target": target,
        "salesItemId": TARGETS[target],
        "queries": [],
        "resources": [],
    }
    pending: dict[str, str] = {}
    driver.get_log("performance")
    driver.get_log("browser")
    driver.get(f"{ORIGIN}/booking/schedule/104036?salesItemId={TARGETS[target]}")
    until = time.monotonic() + 45
    while True:
        page = driver.execute_script(PAGE_JS)
        if "publicText" in page:
            page["publicText"] = public_text(page["publicText"])
        result["page"] = page
        result.setdefault("browserErrors", []).extend(browser_diagnostics(driver))
        result["browserErrors"] = result["browserErrors"][:12]
        result["sourceMatches"] = source_matches(driver.current_url, target)
        # Never retry a challenge by changing network, profile, headers or source.
        if page["challenge"] or page["loginRequired"]:
            result["state"] = "human_verification_required"
            return result
        if not result["sourceMatches"]:
            result["state"] = "unexpected_source"
            return result
        read_queries(driver, pending, result["queries"], result["resources"])
        if any(q.get("accessChallenge") for q in result["queries"]):
            result["state"] = "human_verification_required"
            return result
        paths = {q["path"].rsplit("/", 1)[-1] for q in result["queries"] if q["json"]}
        if (
            page["tableFound"]
            and page["cells"]
            and {"getVenueCalendarList", "getVenueOrderList"} <= paths
        ):
            result["state"] = "query_samples_observed_not_bookability_acceptance"
            return result
        if time.monotonic() >= until:
            result["state"] = "query_acquisition_incomplete"
            return result
        time.sleep(1)


def main() -> int:
    report: dict[str, Any] = {
        "observedAt": datetime.now(UTC).isoformat(),
        "productionReady": False,
        "productionChanged": False,
        "externalTestSends": 0,
        "targets": [],
    }
    driver = None
    with tempfile.TemporaryDirectory(prefix="bawtt-live-") as profile:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            options = Options()
            for arg in (
                f"--user-data-dir={profile}",
                "--window-size=1280,800",
                "--disable-dev-shm-usage",
            ):
                options.add_argument(arg)
            options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
            options.binary_location = shutil.which("chromium") or "/usr/lib/chromium/chromium"
            os.environ.setdefault("DISPLAY", ":0")
            if (Path.home() / ".Xauthority").is_file():
                os.environ.setdefault("XAUTHORITY", str(Path.home() / ".Xauthority"))
            service = Service(shutil.which("chromedriver") or "/usr/local/bin/chromedriver")
            driver = webdriver.Chrome(service=service, options=options)
            driver.set_page_load_timeout(35)
            driver.set_script_timeout(10)
            blocked = False
            for target in TARGETS:
                if blocked:
                    report["targets"].append(
                        {"target": target, "state": "not_attempted_site_challenge"}
                    )
                    continue
                try:
                    result = observe(driver, target)
                except Exception as exc:
                    result = {
                        "target": target,
                        "state": "query_failed",
                        "errorClass": type(exc).__name__,
                    }
                report["targets"].append(result)
                blocked = result["state"] == "human_verification_required"
        except Exception as exc:
            report["errorClass"] = type(exc).__name__
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    report["browserCleanupUnconfirmed"] = True
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    success = len(report["targets"]) == 2 and all(
        t["state"] == "query_samples_observed_not_bookability_acceptance" for t in report["targets"]
    )
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
