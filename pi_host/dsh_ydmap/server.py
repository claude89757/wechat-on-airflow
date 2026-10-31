#!/usr/bin/env python3
"""Local Chromium scrape service for the YDMap tennis venues."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, TypedDict
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

DSH_BOOKING_URL = "https://wxsports.ydmap.cn/booking/schedule/100220?salesItemId=100000"
BAOTI_SALES_ID = "104036"
BAOTI_GROUP_ITEMS = (
    ("outdoor", "室外", "111317"),
    ("indoor", "室内", "103224"),
    ("windrain", "风雨", "111319"),
)
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("YDMAP_LISTEN_PORT", "8788"))
PROFILE = Path(os.environ.get("YDMAP_PROFILE", "/tmp/dsh_ydmap_profile"))
DEBUG_PORT = int(os.environ.get("YDMAP_DEBUG_PORT", "9224"))
SCHEMA_VERSION = 2
SCRAPE_TIMEOUT = 210
SHANGHAI = ZoneInfo("Asia/Shanghai")
UA = (
    "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.7151.119 Safari/537.36"
)
CHROMIUM_BIN = "/usr/lib/chromium/chromium"
CHROMEDRIVER = "/usr/local/bin/chromedriver"
DEFAULT_DAYS = 5
DEFAULT_VENUE = "dsh"
SCRAPE_LOCK = threading.Lock()


def _baoti_group_url(sales_item_id: str) -> str:
    return f"https://bawtt.ydmap.cn/booking/schedule/{BAOTI_SALES_ID}?salesItemId={sales_item_id}"


VENUE_GROUPS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "dsh": (("", "", DSH_BOOKING_URL),),
    "baoti": tuple((key, label, _baoti_group_url(item)) for key, label, item in BAOTI_GROUP_ITEMS),
}

VENUE_NAMES: dict[str, str] = {
    "dsh": "大沙河国际网球交流中心",
    "baoti": "宝安网球中心",
}

FIND_DATE_JS = """
const target = arguments[0];
const nodes = [...document.querySelectorAll('div,span,button,li,a')];
const matches = nodes.filter((el) => {
  const text = (el.innerText || '').trim().split('\\n')[0];
  return text === target && el.offsetParent !== null;
}).map((el) => {
  const box = el.getBoundingClientRect();
  return { el, children: el.children.length, area: box.width * box.height };
});
if (!matches.length) return null;
matches.sort((left, right) => {
  if (left.children !== right.children) return left.children - right.children;
  return right.area - left.area;
});
return matches[0].el;
"""

# Public field shape was recorded by PR223's source diagnostic, workflow run
# 35073589879 (booking-schedule-venue.b6226c5c.js). The current deployment must
# still satisfy these checks. Product-name aliases below are runtime-validated
# catalog fields; fixtures are not proof of today's vendor schema or labels.
EXTRACT_DAY_JS = r"""
const bodyText = document.body && document.body.innerText || '';
function visible(el) {
  if (!el || !el.getBoundingClientRect) return false;
  const box = el.getBoundingClientRect();
  if (box.width <= 0 || box.height <= 0 || box.bottom <= 0 || box.right <= 0 ||
      box.top >= innerHeight || box.left >= innerWidth) return false;
  for (let node = el; node; node = node.parentElement) {
    const style = getComputedStyle(node);
    if (style.display === 'none' || style.visibility === 'hidden' ||
        style.visibility === 'collapse' || Number(style.opacity) === 0 ||
        style.contentVisibility === 'hidden') return false;
  }
  return true;
}
// Slider is the ordinary product/date strip, not a verification challenge.
const captcha = /Access\s+Verification|slide\s+to\s+verify|访问\s*验证|安全\s*验证|人机\s*验证|验证码|滑动\s*验证/i.test(bodyText) ||
  [...document.querySelectorAll('.waf-nc-mask')].some(visible);
const accessError = captcha ? 'captcha' :
  /访问的?频次过快|请求过于频繁|too many requests|rate limit/i.test(bodyText) ? 'rate_limited' :
  /请先登录|登录后查看|sign in to continue/i.test(bodyText) ? 'login_required' : null;
function findByName(vm, name, seen) {
  if (!vm || seen.has(vm)) return null;
  seen.add(vm);
  const current = (vm.$options && (vm.$options.name || vm.$options._componentTag)) || '';
  if (current === name) return vm;
  for (const child of vm.$children || []) {
    const hit = findByName(child, name, seen);
    if (hit) return hit;
  }
  return null;
}
const root = document.querySelector('#app') && document.querySelector('#app').__vue__;
const table = findByName(root, 'ScheduleTable', new Set());
const parent = table && table.$parent;
const params = table && table.params || {};
const item = params.salesItem || {};
function isoDate(value) {
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 1e12 || number >= 1e13) return null;
  return new Date(number + 8 * 3600 * 1000).toISOString().slice(0, 10);
}
function productName(product) {
  // Name fields are read from the selected source object, never from our URL/label.
  for (const key of ['salesItemName', 'itemName', 'name']) {
    if (typeof product[key] === 'string' && product[key].trim()) {
      return {name: product[key].trim(), field: key};
    }
  }
  return {name: null, field: null};
}
const product = productName(item);
const items = parent && parent.serverData && parent.serverData.itemDataList || [];
const catalogItem = items.find(value => String(value.salesItemId) === String(item.salesItemId));
const productInCatalog = !!catalogItem && productName(catalogItem).name === product.name;
// Track only object identities in our own namespace; do not change Vue data,
// intercept requests, replay credentials, or modify verification elements.
const stateKey = '__ydmapReadOnlyDataIdentityV2';
const state = window[stateKey] || (window[stateKey] = {ids: new WeakMap(), next: 1});
function objectId(value) {
  if (!Array.isArray(value)) return null;
  if (!state.ids.has(value)) state.ids.set(value, state.next++);
  return state.ids.get(value);
}
const sourceData = table && table.serverData || {};
const rows = (table && table.rows) || [];
const courts = {};
const courtNames = [];
let cellCount = 0;
rows.forEach((row) => {
  const cells = Array.isArray(row) ? row : Object.values(row || {});
  cells.forEach((col) => {
    if (!col || !col.startTimeText || !col.endTimeText) return;
    cellCount += 1;
    const venue = col.platformInfo && col.platformInfo.venueName;
    if (!venue) return;
    if (!courtNames.includes(venue)) courtNames.push(venue);
    const cls = col.className || '';
    const expired = col.expired === true || col.expired === 1;
    if (expired) return;
    if (col.orderNoBook || col.orderInfo && Object.keys(col.orderInfo).length) return;
    if (/completed|locked|scheduled|inprocess|disabled|expired|not-open|noOpen|fight|max-ball/i.test(cls)) return;
    const ranges = courts[venue] || [];
    if (!ranges.some((item) => item[0] === col.startTimeText && item[1] === col.endTimeText)) {
      ranges.push([col.startTimeText, col.endTimeText]);
    }
    courts[venue] = ranges;
  });
});
return {
  captcha,
  accessError,
  ready: cellCount > 0,
  signature: `${cellCount}:${Object.keys(courts).sort().join(',')}:${JSON.stringify(courts)}`,
  courts,
  courtNames,
  cellCount,
  pageHost: location.hostname,
  selectedDate: isoDate(parent && parent.curDate),
  queryDate: isoDate(params.dateTime),
  selectedProduct: parent?.salesItemId == null ? null : String(parent.salesItemId),
  sourceProduct: item.salesItemId == null ? null : String(item.salesItemId),
  selectedSalesId: parent?.salesId == null ? null : String(parent.salesId),
  sourceSalesId: params.salesId == null ? null : String(params.salesId),
  productName: product.name,
  productNameField: product.field,
  productInCatalog,
  availableDates: (parent && parent.serverData && parent.serverData.dateDataList || [])
    .map(value => isoDate(value.day)).filter(Boolean),
  loadingCounter: table && table.tableLoadingCounter,
  loadGeneration: table && table.tableLoadingFlag,
  dataVersion: {
    platforms: objectId(sourceData.sportPlatformList),
    orders: objectId(sourceData.orderInfoList),
  },
};
"""


def _cleanup_stale_browser() -> None:
    # Candidate deployment must never erase a shared/home directory via a typo.
    resolved = PROFILE.resolve()
    if resolved == Path("/tmp") or not resolved.is_relative_to("/tmp"):
        raise ValueError("YDMAP_PROFILE must be a dedicated directory below /tmp")
    subprocess.run(
        ["pkill", "-f", "--", f"--remote-debugging-port={DEBUG_PORT}([[:space:]]|$)"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    if PROFILE.exists():
        shutil.rmtree(PROFILE, ignore_errors=True)
    PROFILE.mkdir(parents=True, exist_ok=True)


def _start_chromium(url: str) -> subprocess.Popen[Any]:
    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY") or ":0"
    env.setdefault("XAUTHORITY", "/home/claude/.Xauthority")
    env["LANG"] = "zh_CN.UTF-8"
    env["LANGUAGE"] = "zh_CN:zh"
    env["LC_ALL"] = "zh_CN.UTF-8"
    cmd = [
        CHROMIUM_BIN,
        f"--remote-debugging-port={DEBUG_PORT}",
        "--remote-allow-origins=*",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-sync",
        "--lang=zh-CN",
        "--accept-lang=zh-CN,zh,en-US,en",
        f"--user-agent={UA}",
        "--window-size=1280,800",
        "--window-position=80,40",
        url,
    ]
    return subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _wait_devtools(timeout: float = 40) -> None:
    url = f"http://127.0.0.1:{DEBUG_PORT}/json/version"
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                json.loads(resp.read().decode())
                return
        except Exception as exc:
            last = str(exc)
            time.sleep(0.4)
    raise RuntimeError(f"devtools not ready: {last}")


def _stop_driver_service(service: Any) -> None:
    process = getattr(service, "process", None)
    if process is None:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass
    service.process = None


def _attach(timeout: float = 30) -> webdriver.Remote:
    from selenium.webdriver.remote.remote_connection import RemoteConnection

    # Configure the connection before NEW_SESSION. Calling the deprecated
    # class-level set_timeout before a connection exists fails on recent
    # Selenium; setting it after Chrome() leaves session startup unbounded.
    opts = Options()
    opts.debugger_address = f"127.0.0.1:{DEBUG_PORT}"
    service = Service(CHROMEDRIVER)
    watchdog = threading.Timer(timeout, _stop_driver_service, args=(service,))
    watchdog.daemon = True
    watchdog.start()
    try:
        service.start()
        connection = RemoteConnection(service.service_url, keep_alive=False)
        connection.set_timeout(10)
        driver = webdriver.Remote(command_executor=connection, options=opts)
        driver._ydmap_service = service
        driver.set_page_load_timeout(20)
        driver.set_script_timeout(8)
        return driver
    except Exception:
        _stop_driver_service(service)
        raise
    finally:
        watchdog.cancel()


def _stop(proc: subprocess.Popen[Any], driver: webdriver.Remote | None) -> None:
    if driver is not None:
        try:
            driver.quit()
        except Exception:
            pass
        _stop_driver_service(getattr(driver, "_ydmap_service", None))
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()


def _extract_day(driver: webdriver.Remote) -> dict[str, Any]:
    payload = driver.execute_script(EXTRACT_DAY_JS)
    return payload if isinstance(payload, dict) else {}


class VenueIdentity(TypedDict):
    host: str
    sales_id: str
    sales_item_id: str
    label: str


def _snapshot_issue(
    payload: dict[str, Any],
    *,
    host: str,
    sales_id: str,
    sales_item_id: str,
    label: str,
    expected_date: str | None = None,
    previous: dict[str, Any] | None = None,
) -> str | None:
    if payload.get("captcha"):
        return "captcha"
    if payload.get("accessError"):
        return str(payload["accessError"])
    if (
        not payload.get("ready")
        or type(payload.get("cellCount")) is not int
        or payload["cellCount"] < 1
    ):
        return "schedule_not_ready"
    if payload.get("pageHost") != host:
        return "venue_host_mismatch"
    if payload.get("selectedSalesId") != sales_id or payload.get("sourceSalesId") != sales_id:
        return "venue_id_mismatch"
    if (
        payload.get("selectedProduct") != sales_item_id
        or payload.get("sourceProduct") != sales_item_id
    ):
        return "product_id_mismatch"
    product_name = payload.get("productName")
    if not isinstance(product_name, str) or not product_name or not payload.get("productInCatalog"):
        return "product_name_unverified"
    if label and label not in product_name:
        return "product_name_mismatch"
    selected = payload.get("selectedDate")
    if not selected or selected != payload.get("queryDate"):
        return "date_identity_mismatch"
    if expected_date is not None and selected != expected_date:
        return "date_not_selected"
    if payload.get("loadingCounter") != 0:
        return "schedule_loading"
    generation = payload.get("loadGeneration")
    version = payload.get("dataVersion")
    if (
        type(generation) is not int
        or generation < 1
        or not isinstance(version, dict)
        or any(
            type(version.get(key)) is not int or version[key] < 1 for key in ("platforms", "orders")
        )
    ):
        return "source_identity_unavailable"
    if previous is not None:
        old = previous.get("dataVersion") or {}
        # Both public data arrays must have been replaced by a new successful
        # generation. A changed selected tab or changed availability signature
        # alone does not prove that the response belongs to that date.
        if generation <= previous.get("loadGeneration", 0) or any(
            version[key] == old.get(key) for key in ("platforms", "orders")
        ):
            return "source_not_refreshed"
    names = payload.get("courtNames")
    courts = payload.get("courts")
    if (
        not isinstance(names, list)
        or not names
        or any(not isinstance(name, str) or not name.strip() for name in names)
        or not isinstance(courts, dict)
        or not set(courts).issubset(names)
    ):
        return "court_identity_unavailable"
    if label and any(
        other in name for name in names for other in ("室外", "室内", "风雨") if other != label
    ):
        return "court_group_mismatch"
    return None


def _wait_for_schedule(
    driver: webdriver.Remote,
    timeout: float = 45,
    *,
    deadline: float | None = None,
    **identity: Any,
) -> dict[str, Any]:
    end = (
        min(time.monotonic() + timeout, deadline)
        if deadline is not None
        else time.monotonic() + timeout
    )
    last: dict[str, Any] = {}
    issue: str | None = "schedule_not_ready"
    while time.monotonic() < end:
        last = _extract_day(driver)
        issue = _snapshot_issue(last, **identity)
        if issue is None:
            return last
        if issue in {"captcha", "rate_limited", "login_required"}:
            return {**last, "ready": False, "error": issue}
        time.sleep(min(1.0, max(0.0, end - time.monotonic())))
    # Never return a ready stale snapshot when the date switch timed out.
    return {**last, "ready": False, "error": issue or "schedule_timeout"}


def _remaining(deadline: float, maximum: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("scrape_deadline_exceeded")
    return min(remaining, maximum)


def _prefixed_court_name(label: str, court: str) -> str:
    """Disambiguate courts whose raw name omits its venue group."""
    name = str(court).strip()
    if not label or not name or label in name:
        return name
    return f"{label}{name}"


def _stop_with_error(
    *,
    error: str,
    venue: str,
    payload: dict[str, Any] | None = None,
    captcha: bool = False,
) -> dict[str, Any]:
    observed = payload or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "venue": venue,
        "ok": False,
        "captcha": captcha,
        "error": error,
        # A partial group/date result must never become an observation.
        "days": [],
        "diagnostics": {
            key: observed.get(key)
            for key in (
                "pageHost",
                "selectedDate",
                "queryDate",
                "selectedSalesId",
                "sourceSalesId",
                "selectedProduct",
                "sourceProduct",
                "productName",
                "productNameField",
                "productInCatalog",
                "loadingCounter",
                "loadGeneration",
                "dataVersion",
                "courtNames",
                "cellCount",
            )
            if key in observed
        },
    }


def _days_payload(
    days: dict[str, dict[str, list[list[str]]]],
    names: dict[str, list[str]],
    evidence: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    return [
        {
            "date": booking_date,
            "courts": days[booking_date],
            "court_names": names.get(booking_date) or [],
            "groups": evidence.get(booking_date) or [],
        }
        for booking_date in sorted(days)
    ]


def scrape_available_slots(venue: str = DEFAULT_VENUE, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    groups = VENUE_GROUPS.get(venue)
    if not groups:
        return _stop_with_error(error=f"unknown_venue:{venue}", venue=venue)
    days = min(max(days, 1), 7)
    # Reserve driver/browser cleanup time inside the caller's 240-second limit.
    budget = min(SCRAPE_TIMEOUT, 135) if venue == "dsh" else SCRAPE_TIMEOUT
    deadline = time.monotonic() + budget - 30
    today = datetime.now(SHANGHAI).date()
    requested = [(today + timedelta(days=offset)).isoformat() for offset in range(days)]
    proc = None
    driver = None
    collected: dict[str, dict[str, list[list[str]]]] = {}
    court_names: dict[str, list[str]] = {}
    evidence: dict[str, list[dict[str, Any]]] = {}
    try:
        _cleanup_stale_browser()
        proc = _start_chromium(groups[0][2])
        _wait_devtools(timeout=_remaining(deadline, 40))
        driver = _attach(timeout=_remaining(deadline, 30))
        for index, (key, label, url) in enumerate(groups):
            _remaining(deadline, 20)
            if index > 0:
                driver.set_page_load_timeout(_remaining(deadline, 20))
                driver.get(url)
            parsed = urlparse(url)
            identity: VenueIdentity = {
                "host": parsed.hostname or "",
                "sales_id": parsed.path.rsplit("/", 1)[-1],
                "sales_item_id": parse_qs(parsed.query)["salesItemId"][0],
                "label": label,
            }
            payload = _wait_for_schedule(driver, deadline=deadline, **identity)
            if not payload.get("ready"):
                return _stop_with_error(
                    error=payload.get("error") or "schedule_not_ready",
                    venue=venue,
                    payload=payload,
                    captcha=bool(payload.get("captcha")),
                )
            initial_issue = _snapshot_issue(payload, **identity)
            if initial_issue:
                return _stop_with_error(error=initial_issue, venue=venue, payload=payload)
            order = list(requested)
            if payload["selectedDate"] == order[0]:
                if len(order) > 1:
                    order[0], order[1] = order[1], order[0]
                else:
                    alternatives = [
                        value for value in payload.get("availableDates", []) if value != order[0]
                    ]
                    if not alternatives:
                        return _stop_with_error(
                            error="refresh_date_unavailable", venue=venue, payload=payload
                        )
                    order.insert(0, alternatives[0])
            for booking_iso in order:
                _remaining(deadline, 25)
                if booking_iso not in payload.get("availableDates", []):
                    return _stop_with_error(
                        error="requested_date_unavailable", venue=venue, payload=payload
                    )
                element = driver.execute_script(FIND_DATE_JS, booking_iso[5:])
                if element is None:
                    return _stop_with_error(error=f"date_tab_not_found:{booking_iso}", venue=venue)
                # Native WebDriver click respects overlays/hit testing. Never
                # remove a WAF mask or force a JavaScript click through it.
                element.click()
                previous = payload
                payload = _wait_for_schedule(
                    driver,
                    timeout=25,
                    deadline=deadline,
                    expected_date=booking_iso,
                    previous=previous,
                    **identity,
                )
                if not payload.get("ready"):
                    return _stop_with_error(
                        error=payload.get("error") or "schedule_not_ready",
                        venue=venue,
                        payload=payload,
                        captcha=bool(payload.get("captcha")),
                    )
                issue = _snapshot_issue(
                    payload, expected_date=booking_iso, previous=previous, **identity
                )
                if issue:
                    return _stop_with_error(error=issue, venue=venue, payload=payload)
                if booking_iso not in requested:
                    continue
                bucket = collected.setdefault(booking_iso, {})
                known = court_names.setdefault(booking_iso, [])
                group_names = [_prefixed_court_name(label, name) for name in payload["courtNames"]]
                for name in group_names:
                    if name not in known:
                        known.append(name)
                for court, ranges in payload["courts"].items():
                    name = _prefixed_court_name(label, str(court))
                    bucket[name] = ranges
                evidence.setdefault(booking_iso, []).append(
                    {
                        "key": key,
                        "sales_item_id": payload["sourceProduct"],
                        "source_sales_id": payload["sourceSalesId"],
                        "source_host": payload["pageHost"],
                        "product_name": payload["productName"],
                        "product_name_field": payload["productNameField"],
                        "source_date": payload["queryDate"],
                        "selected_date": payload["selectedDate"],
                        "court_names": group_names,
                        "cell_count": payload["cellCount"],
                        "load_generation": payload["loadGeneration"],
                        "data_version": payload["dataVersion"],
                        "freshness": "both_source_arrays_replaced_after_date_selection",
                    }
                )
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "captcha": False,
            "venue": venue,
            "venue_name": VENUE_NAMES.get(venue, venue),
            "days": _days_payload(collected, court_names, evidence),
        }
    except Exception as exc:
        return _stop_with_error(error=type(exc).__name__, venue=venue)
    finally:
        if proc is not None:
            _stop(proc, driver)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        print(f"[dsh-ydmap] {format % args}")

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send_json(
                200,
                {
                    "ok": True,
                    "service": "dsh_ydmap",
                    "protocolVersion": SCHEMA_VERSION,
                    "deploymentCommit": os.environ.get("YDMAP_DEPLOYMENT_COMMIT"),
                    "sourceSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    "venues": sorted(VENUE_GROUPS),
                    "busy": SCRAPE_LOCK.locked(),
                },
            )
            return
        if parsed.path != "/inspect":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        query = parse_qs(parsed.query)
        venue = str((query.get("venue") or [DEFAULT_VENUE])[0]).strip() or DEFAULT_VENUE
        try:
            days = int((query.get("days") or [str(DEFAULT_DAYS)])[0])
        except ValueError:
            days = DEFAULT_DAYS
        if not SCRAPE_LOCK.acquire(blocking=False):
            self._send_json(429, _stop_with_error(error="busy", venue=venue))
            return
        try:
            payload = scrape_available_slots(venue, days)
            self._send_json(200 if payload.get("ok") else 503, payload)
        except Exception as exc:
            self._send_json(500, _stop_with_error(error=type(exc).__name__, venue=venue))
        finally:
            SCRAPE_LOCK.release()


def main() -> None:
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(f"[dsh-ydmap] listening on {LISTEN_HOST}:{LISTEN_PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
