#!/usr/bin/env python3
"""Local Chromium scrape service for the YDMap tennis venues."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
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
PROFILE = Path(os.environ.get("YDMAP_PROFILE", "/tmp/pi-ydmap-service-profile-v2"))
DEBUG_PORT = int(os.environ.get("YDMAP_DEBUG_PORT", "9224"))
SCHEMA_VERSION = 2
SCRAPE_TIMEOUT = 210
DRIVER_HTTP_TIMEOUT = 30
DRIVER_CLEANUP_TIMEOUT = 5
UI_CAPTURE_MAX_BYTES = 256 * 1024
SHANGHAI = ZoneInfo("Asia/Shanghai")
CHROMIUM_BIN = "/usr/lib/chromium/chromium"
CHROMEDRIVER = "/usr/local/bin/chromedriver"
DEFAULT_DAYS = 5
DEFAULT_VENUE = "dsh"
BAOTI_PRODUCT_INTERVAL_SECONDS = 30
SCRAPE_LOCK = threading.Lock()
VERIFICATION_AVAILABLE = os.environ.get("YDMAP_AUTHORIZED_VERIFICATION") == "1"
SOURCE_METHODS = (
    "isAvailableStatic",
    "textFun",
    "isNoBook",
    "classObj",
    "closeMsg",
    "sellerMessage",
    "isTicketDisabled",
)
SOURCE_METHOD_BYTES = 4096
SOURCE_TOTAL_BYTES = 24 * 1024
SOURCE_CLASSES = frozenset(
    "col-inprocess col-completed col-locked col-scheduled orderNoBook expired noOpen disabled "
    "not-open col-fight-ing col-fight-request col-fight-respond fight-request fight-request-ing "
    "fight-respond col-max-ball col-ball selected".split()
)
SOURCE_LITERAL_ALLOWLIST = SOURCE_CLASSES | frozenset(
    {
        "",
        " ",
        "/",
        "-",
        ":",
        "(",
        ")",
        "元",
        "分钟",
        "免费",
        "预订中",
        "已预订",
        "已过期",
        "已占用",
        "约战中",
        "已约战",
        "已应战",
        "未开放",
        "不可预约",
        "已售罄",
        "剩余",
        "可约",
        "undefined",
        "object",
        "function",
        "string",
        "number",
        "boolean",
        "length",
        "row",
        "price",
        "platformInfo",
        "venueName",
        "orderInfo",
        "className",
        "onlineBooking",
        "salesItemId",
        "open",
        "closed",
        "enabled",
        "disabled",
    }
)
SOURCE_ONLINE_ENUMS = frozenset(
    word
    for word in ("open", "closed", "enabled", "disabled")
    for word in (word, word.upper(), word.title())
) | {"开放", "关闭", "开启", "不开放"}


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
const challengeText = /Access\s+Verification|slide\s+to\s+verify|访问\s*验证|安全\s*验证|人机\s*验证|验证码|滑动\s*验证/i.test(bodyText);
const challengeMaskVisible = [...document.querySelectorAll('.waf-nc-mask')].some(visible);
const captcha = challengeText || challengeMaskVisible;
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
const sourceCells = [];
const includedCells = new Set();
let cellCount = 0;
rows.forEach((row) => {
  const cells = Array.isArray(row) ? row : Object.values(row || {});
  cells.forEach((col) => {
    if (!col || !col.startTimeText || !col.endTimeText) return;
    cellCount += 1;
    sourceCells.push(col);
    const venue = col.platformInfo && col.platformInfo.venueName;
    if (!venue) return;
    if (!courtNames.includes(venue)) courtNames.push(venue);
    // Use the page's read-only booking predicate, not a subset of CSS states.
    // It also checks price, online booking, release time and merged cells.
    // Missing/changed predicates fail the scrape rather than imply empty courts.
    if (!accessError) {
      if (typeof table.isAvailableStatic !== 'function') {
        throw new Error('bookability_predicate_unavailable');
      }
      if (table.isTicket !== false) throw new Error('bookability_product_type_unverified');
      const available = table.isAvailableStatic(col);
      if (typeof available !== 'boolean') throw new Error('bookability_predicate_invalid');
      if (!available || col.orderInfo != null) return;
    } else {
      return;
    }
    const cls = col.className || '';
    const expired = col.expired === true || col.expired === 1;
    if (expired) return;
    if (col.orderNoBook || col.orderInfo && Object.keys(col.orderInfo).length) return;
    if (/completed|locked|scheduled|inprocess|disabled|expired|not-open|noOpen|fight|max-ball/i.test(cls)) return;
    includedCells.add(col);
    const ranges = courts[venue] || [];
    if (!ranges.some((item) => item[0] === col.startTimeText && item[1] === col.endTimeText)) {
      ranges.push([col.startTimeText, col.endTimeText]);
    }
    courts[venue] = ranges;
  });
});
const result = {
  captcha,
  challengeText,
  challengeMaskVisible,
  documentComplete: document.readyState === 'complete',
  scheduleComponentPresent: !!table,
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
if (arguments[0] === true && !accessError) {
  const methodNames = ['isAvailableStatic', 'textFun', 'isNoBook', 'classObj', 'closeMsg', 'sellerMessage', 'isTicketDisabled'];
  const pending = table ? [table] : [];
  const seen = new Set();
  const covered = new Set();
  const components = [];
  const methods = [];
  const definitions = new Map();
  const encoder = new TextEncoder();
  let scanTruncated = false;
  let sourceTruncated = false;
  let remaining = 24576;
  function definition(vm, name) {
    for (const kind of ['methods', 'computed']) {
      const entry = Object.getOwnPropertyDescriptor(vm.$options?.[kind] || {}, name)?.value;
      const fn = typeof entry === 'function' ? entry :
        kind === 'computed' ? Object.getOwnPropertyDescriptor(entry || {}, 'get')?.value : null;
      if (typeof fn === 'function') return {fn, kind: kind === 'methods' ? 'method' : 'computed'};
    }
    return null;
  }
  while (pending.length && seen.size < 256) {
    const vm = pending.shift();
    if (!vm || seen.has(vm)) continue;
    seen.add(vm);
    const children = Array.isArray(vm.$children) ? vm.$children : [];
    const room = Math.max(0, 256 - seen.size - pending.length);
    pending.push(...children.slice(0, room));
    if (children.length > room) scanTruncated = true;
    const found = methodNames.map(name => ({name, definition: definition(vm, name)}));
    if (!found.some(value => value.definition)) continue;
    if (components.length >= 16) { scanTruncated = true; continue; }
    const index = components.length;
    // Read the already-bound row prop only. Never evaluate renderer/computed
    // functions, call booking handlers, or assume offscreen rows are mounted.
    const bound = vm.row;
    const mounted = vm._isMounted === true && vm._isDestroyed !== true && vm.$el?.isConnected === true;
    const matched = mounted && Array.isArray(bound) ? sourceCells.filter(col => bound.includes(col)) : [];
    matched.forEach(col => covered.add(col));
    const rawName = vm.$options?.name || vm.$options?._componentTag;
    components.push({
      index, name: typeof rawName === 'string' && /^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(rawName) ? rawName : null,
      matched_cell_count: matched.length,
      methods: Object.fromEntries(found.map(value => [value.name, !!value.definition])),
    });
    for (const {name, definition: item} of found) {
      if (!item) continue;
      const key = name + ':' + item.kind;
      const previous = definitions.get(item.fn)?.get(key);
      if (previous !== undefined) { methods[previous].component_indices.push(index); continue; }
      if (methods.length >= 24) { sourceTruncated = true; continue; }
      const raw = Function.prototype.toString.call(item.fn);
      const bytes = encoder.encode(raw);
      const limit = Math.min(4096, remaining);
      const source = new TextDecoder().decode(bytes.slice(0, limit), {stream: true});
      const emitted = encoder.encode(source).length;
      const truncated = bytes.length > emitted;
      remaining -= emitted;
      sourceTruncated ||= truncated;
      const record = {name, kind: item.kind, component_indices: [index], source,
        original_bytes: bytes.length, truncated};
      if (!definitions.has(item.fn)) definitions.set(item.fn, new Map());
      definitions.get(item.fn).set(key, methods.length);
      methods.push(record);
    }
  }
  scanTruncated ||= pending.length > 0;
  const matched = sourceCells.filter(col => covered.has(col)).length;
  const samples = [];
  for (const included of [true, false]) {
    const col = sourceCells.find(value => includedCells.has(value) === included && value.platformInfo?.venueName);
    if (!col) continue;
    const rawOnline = col.platformInfo.onlineBooking;
    samples.push({included, court: col.platformInfo.venueName, start: col.startTimeText, end: col.endTimeText,
      known_classes: typeof col.className === 'string' ? col.className.split(/\s+/).slice(0, 32) : [],
      expired: col.expired === true || col.expired === 1, order_no_book: !!col.orderNoBook,
      has_order: !!col.orderInfo && Object.keys(col.orderInfo).length > 0, has_price: !!col.priceBean,
      online_booking: ['string', 'number', 'boolean'].includes(typeof rawOnline) ? rawOnline : null,
      online_booking_redacted: rawOnline != null && !['string', 'number', 'boolean'].includes(typeof rawOnline),
    });
  }
  result.sourceEvidence = {schema_version: 1, bookability_verified: false,
    source_cell_count: sourceCells.length, matched_cell_count: matched,
    unmatched_cell_count: sourceCells.length - matched,
    coverage_complete: !scanTruncated && sourceCells.length > 0 && matched === sourceCells.length,
    component_scan_truncated: scanTruncated, source_truncated: sourceTruncated,
    components, methods, samples};
}
return result;
"""


def _cleanup_stale_browser(profile: Path | None = None) -> None:
    # Never reuse or chmod a shared/home profile via a typo or final symlink.
    temporary_root = Path("/tmp").resolve()
    profile = profile or PROFILE
    base = PROFILE.resolve()
    resolved = profile.resolve()
    if (
        PROFILE.is_symlink()
        or profile.is_symlink()
        or base == temporary_root
        or not base.is_relative_to(temporary_root)
        or not resolved.is_relative_to(base)
    ):
        raise ValueError("YDMAP_PROFILE must be a dedicated directory below /tmp")
    subprocess.run(
        ["pkill", "-f", "--", f"--remote-debugging-port={DEBUG_PORT}([[:space:]]|$)"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1)
    # Let Chromium retain its own site state/cache across inspections. This is
    # the service's dedicated profile, never a copied personal browser profile.
    PROFILE.mkdir(parents=True, exist_ok=True, mode=0o700)
    PROFILE.chmod(0o700)
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile.chmod(0o700)


def _start_chromium(url: str, *, profile: Path | None = None) -> subprocess.Popen[Any]:
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
        f"--user-data-dir={profile or PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-sync",
        "--lang=zh-CN",
        "--accept-lang=zh-CN,zh,en-US,en",
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
    from selenium.webdriver.remote.client_config import ClientConfig
    from selenium.webdriver.remote.remote_connection import RemoteConnection

    # Configure the connection before NEW_SESSION. Calling the deprecated
    # class-level set_timeout before a connection exists fails on recent
    # Selenium; setting it after Chrome() leaves session startup unbounded.
    opts = Options()
    opts.debugger_address = f"127.0.0.1:{DEBUG_PORT}"
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    service = Service(CHROMEDRIVER)
    watchdog = threading.Timer(timeout, _stop_driver_service, args=(service,))
    watchdog.daemon = True
    watchdog.start()
    try:
        service.start()
        # The wire timeout must exceed the 20-second page-load limit, allowing
        # ChromeDriver to return its own bounded error instead of losing the
        # local command response. The startup watchdog still bounds NEW_SESSION.
        config = ClientConfig(
            remote_server_addr=service.service_url,
            keep_alive=False,
            timeout=DRIVER_HTTP_TIMEOUT,
        )
        connection = RemoteConnection(client_config=config)
        driver = webdriver.Remote(command_executor=connection, options=opts)
        driver._ydmap_service = service
        driver._ydmap_client_config = config
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
        config = getattr(driver, "_ydmap_client_config", None)
        if config is not None:
            config.timeout = DRIVER_CLEANUP_TIMEOUT
        try:
            # Closing our own final tab lets Chromium flush its profile before
            # the fallback process termination. Remote-attached quit alone need
            # not close the independently launched browser.
            driver.close()
        except Exception:
            pass
        try:
            driver.quit()
        except Exception:
            pass
        _stop_driver_service(getattr(driver, "_ydmap_service", None))
    try:
        proc.wait(timeout=5)
        return
    except Exception:
        pass
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except Exception:
        proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()


def _extract_day(driver: webdriver.Remote, *, source_evidence: bool = False) -> dict[str, Any]:
    payload = driver.execute_script(EXTRACT_DAY_JS, source_evidence)
    return payload if isinstance(payload, dict) else {}


def _utf8_prefix(value: str, limit: int) -> str:
    return value.encode("utf-8")[: max(0, limit)].decode("utf-8", errors="ignore")


def _regexp_end(source: str, start: int) -> int | None:
    index = start + 1
    in_class = False
    while index < len(source) and source[index] not in "\r\n":
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == "[":
            in_class = True
        elif source[index] == "]":
            in_class = False
        elif source[index] == "/" and not in_class:
            index += 1
            while index < len(source) and source[index] in "dgimsuvy":
                index += 1
            return index
        index += 1
    return None


def _literal_end(source: str, start: int, *, template: bool = False, depth: int = 0) -> int:
    """Skip literal contents, including nested template expressions, without executing JS."""
    if depth > 16:
        return len(source)
    quote = source[start]
    index = start + 1
    braces = 0
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if template and not braces and source.startswith("${", index):
            braces = 1
            index += 2
            continue
        if template and braces:
            if char in "\"'`":
                index = _literal_end(source, index, template=char == "`", depth=depth + 1)
                continue
            if source.startswith("//", index):
                end = source.find("\n", index + 2)
                index = len(source) if end < 0 else end + 1
                continue
            if source.startswith("/*", index):
                end = source.find("*/", index + 2)
                index = len(source) if end < 0 else end + 2
                continue
            if char == "/":
                regex_end = _regexp_end(source, index)
                if regex_end is not None:
                    index = regex_end
                    continue
            if char == "{":
                braces += 1
            elif char == "}":
                braces -= 1
            index += 1
            continue
        if char == quote:
            return index + 1
        index += 1
    return len(source)


def _sanitize_function_source(source: str) -> tuple[str, bool, bool]:
    """Keep reviewable static code, with no arbitrary literal/comment contents."""
    output: list[str] = []
    index = 0
    redacted = False
    incomplete = False
    while index < len(source):
        char = source[index]
        if source.startswith(("//", "/*"), index):
            block = source[index + 1] == "*"
            end = source.find("*/" if block else "\n", index + 2)
            index = len(source) if end < 0 else end + (2 if block else 1)
            output.append(" ")
            redacted = True
        elif char in "\"'`":
            end = _literal_end(source, index, template=char == "`")
            raw = source[index + 1 : max(index + 1, end - 1)]
            closed = end > index + 1 and source[end - 1] == char
            allowed = (
                char != "`"
                and closed
                and "\\" not in raw
                and (raw in SOURCE_LITERAL_ALLOWLIST or re.fullmatch(r"\d{1,3}", raw) is not None)
            )
            value = raw if allowed else "[redacted template]" if char == "`" else "[redacted]"
            output.append(json.dumps(value, ensure_ascii=False))
            redacted |= not allowed
            incomplete |= not closed
            index = end
        elif char == "/":
            # Conservatively omit regexp contents. An ambiguous division tail
            # may be omitted too; that is reported as incomplete, never inferred.
            regex_end = _regexp_end(source, index)
            closed = regex_end is not None
            index = regex_end if regex_end is not None else len(source)
            output.append('"[redacted regex]"')
            redacted = True
            incomplete |= not closed
        elif char.isascii() and (char.isalpha() or char in "_$"):
            match = re.match(r"[A-Za-z_$][A-Za-z0-9_$]*", source[index:])
            assert match is not None
            word = match[0]
            output.append(word if len(word) <= 64 else "redactedIdentifier")
            redacted |= len(word) > 64
            index += len(word)
        elif char.isascii() and char.isdigit():
            match = re.match(
                r"(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", source[index:]
            )
            assert match is not None
            number = match[0]
            output.append(number if len(number) <= 6 else "0")
            redacted |= len(number) > 6
            index += len(number)
        else:
            if ord(char) >= 32 or char in "\n\r\t":
                output.append(char)
            else:
                redacted = True
            index += 1
    return "".join(output), redacted, incomplete


def _source_evidence(raw: dict[str, Any], label: str, budget: dict[str, Any]) -> dict[str, Any]:
    """Bound and sanitize optional diagnostics before any HTTP response is built."""
    result = {
        key: raw[key]
        for key in (
            "schema_version",
            "bookability_verified",
            "source_cell_count",
            "matched_cell_count",
            "unmatched_cell_count",
            "coverage_complete",
            "component_scan_truncated",
            "source_truncated",
        )
    }
    result["bookability_verified"] = False
    result["components"] = raw.get("components", [])[:16]
    result["methods"] = []
    for record in raw.get("methods", [])[:24]:
        if record.get("name") not in SOURCE_METHODS or record.get("kind") not in {
            "method",
            "computed",
        }:
            continue
        source, redacted, incomplete = _sanitize_function_source(str(record.get("source") or ""))
        canonical = _utf8_prefix(source, SOURCE_METHOD_BYTES)
        truncated = bool(record.get("truncated")) or incomplete or canonical != source
        full_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        reused = (record["name"], full_hash) in budget["seen"]
        emitted = "" if reused else _utf8_prefix(canonical, budget["remaining"])
        if not reused:
            truncated |= emitted != canonical
            full_hash = hashlib.sha256(emitted.encode("utf-8")).hexdigest()
            budget["seen"].add((record["name"], full_hash))
            budget["remaining"] -= len(emitted.encode("utf-8"))
        result["source_truncated"] |= truncated
        result["methods"].append(
            {
                "component_indices": record["component_indices"][:16],
                "name": record["name"],
                "kind": record["kind"],
                "sha256": full_hash,
                "source": emitted,
                "original_bytes": record["original_bytes"],
                "emitted_bytes": len(emitted.encode("utf-8")),
                "truncated": truncated,
                "redacted": redacted,
                "reused": reused,
            }
        )
    result["samples"] = []
    for sample in raw.get("samples", [])[:2]:
        online = sample.get("online_booking")
        safe_online = (
            online is None
            or type(online) is bool
            or (type(online) in (int, float) and -1000 <= online <= 1000)
            or (
                isinstance(online, str)
                and (
                    online in SOURCE_ONLINE_ENUMS
                    or re.fullmatch(r"-?\d{1,3}(?:\.\d{1,3})?", online)
                )
            )
        )
        if not all(isinstance(sample.get(key), str) for key in ("court", "start", "end")):
            continue
        if not re.fullmatch(r"[\w\u3400-\u9fff ·.()（）-]{1,120}", sample["court"]):
            continue
        if not all(re.fullmatch(r"\d{2}:\d{2}", sample[key]) for key in ("start", "end")):
            continue
        result["samples"].append(
            {
                key: bool(sample.get(key))
                for key in ("included", "expired", "order_no_book", "has_order", "has_price")
            }
            | {
                "court": _prefixed_court_name(label, sample["court"]),
                "start": sample["start"],
                "end": sample["end"],
                "known_classes": sorted(set(sample.get("known_classes", [])) & SOURCE_CLASSES),
                "online_booking": online if safe_online else None,
                "online_booking_redacted": bool(sample.get("online_booking_redacted"))
                or not safe_online,
            }
        )
    return result


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
        # A product switch can mount a new table with a fresh generation counter.
        # Both actual source arrays must still be new; a relabelled old table fails.
        product_changed = isinstance(previous.get("sourceProduct"), str) and (
            payload.get("sourceProduct") != previous["sourceProduct"]
        )
        if (not product_changed and generation <= previous.get("loadGeneration", 0)) or any(
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
    verification: dict[str, Any] | None = None,
    phase: str = "initial_schedule",
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
            if verification is not None and verification["attempted"]:
                verification["outcome"] = "passed"
            return last
        if (
            issue == "captcha"
            and verification is not None
            and verification["outcome"] == "not_needed"
        ):
            if _normal_verification_once(driver, verification):
                time.sleep(min(3, max(0, end - time.monotonic())))
                continue
        if issue in {"captcha", "rate_limited", "login_required"}:
            return {
                **last,
                "accessDiagnostics": _access_diagnostics(driver),
                "ready": False,
                "error": issue,
                "failurePhase": phase,
                "requestedProduct": identity.get("sales_item_id"),
            }
        time.sleep(min(1.0, max(0.0, end - time.monotonic())))
    # Never return a ready stale snapshot when the date switch timed out.
    return {
        **last,
        "accessDiagnostics": _access_diagnostics(driver),
        "ready": False,
        "error": issue or "schedule_timeout",
        "failurePhase": phase,
        "requestedProduct": identity.get("sales_item_id"),
    }


def _remaining(deadline: float, maximum: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("scrape_deadline_exceeded")
    return min(remaining, maximum)


VERIFICATION_CONTROL_JS = r"""
// Inspect only the rendered verification UI. Never call provider callbacks,
// modify the DOM, manufacture events/tokens, or inspect cookies.
if (location.hostname !== 'bawtt.ydmap.cn') return {status: 'wrong_host'};
const visible = el => el && el.getClientRects().length &&
  getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
const roots = [...document.querySelectorAll('.waf-nc-mask, #WAF_NC_WRAPPER')].filter(visible);
if (!roots.length) return {status: 'root_missing'};
const controls = roots.flatMap(root => [...root.querySelectorAll('[role="slider"], [aria-label="滑块"]')]);
const unique = [...new Set(controls)].filter(visible);
if (!unique.length) return {status: 'controls_missing'};
if (unique.length !== 1) return {status: 'ambiguous_controls'};
const handle = unique[0];
const track = handle.parentElement;
const instruction = (track.innerText || '').replace(/\s+/g, '');
if (!/请.*(?:按住|向右|拖动).*滑块|请.*滑块.*(?:拖动|向右)|请向右滑动验证|slide.*(?:right|verify)/i.test(instruction)) return {status: 'instruction_unrecognized'};
const h = handle.getBoundingClientRect(), t = track.getBoundingClientRect();
const x = t.right - h.width / 2 - 2;
const distance = x - (h.left + h.width / 2);
if (distance < 50 || distance > 600 || h.height < 10 || h.height > 100 ||
    h.top < t.top || h.bottom > t.bottom || x >= innerWidth) return {status: 'geometry_invalid'};
const hit = document.elementFromPoint(h.left + h.width / 2, h.top + h.height / 2);
if (hit !== handle && !handle.contains(hit)) return {status: 'control_obstructed'};
return {status: 'ready', handle, distance: Math.round(distance)};
"""


ACCESS_DIAGNOSTIC_JS = r"""
// Export counts only, never page text, URLs, attributes or challenge material.
const visible = el => el.getClientRects().length &&
  getComputedStyle(el).visibility !== 'hidden' && getComputedStyle(el).display !== 'none';
const roots = [...document.querySelectorAll('.waf-nc-mask, #WAF_NC_WRAPPER')].filter(visible);
const inside = selector => [...new Set(roots.flatMap(root => [...root.querySelectorAll(selector)]))];
const frames = inside('iframe');
const first = {
  documentHidden: Number(document.hidden),
  documentFocused: Number(document.hasFocus()),
  appRootPresent: Number(!!document.querySelector('#app')),
  vueRootPresent: Number(!!document.querySelector('#app')?.__vue__),
  scriptReferences: document.scripts.length,
  maskRoots: roots.length,
  maskChildren: roots.reduce((n, root) => n + root.children.length, 0),
  semanticHandles: inside('[role="slider"], [aria-label="滑块"]').filter(visible).length,
  legacyHandles: inside('.nc_iconfont.btn_slide, [id$="_n1z"]').filter(visible).length,
  frames: frames.length,
  accessibleFrames: frames.filter(frame => {try {return !!frame.contentDocument;} catch (_) {return false;}}).length,
  verificationScripts: [...document.scripts].filter(script => /(?:captcha|nocaptcha|awsc|\/nc\/|waf)/i.test(script.src)).length
};
// Allow asynchronous challenge rendering to settle without another navigation,
// request replay, or interaction. WebDriver's eight-second script limit applies.
return new Promise(resolve => setTimeout(() => resolve({...first,
  settledLegacyHandles: inside('.nc_iconfont.btn_slide, [id$="_n1z"]').filter(visible).length,
  settledSemanticHandles: inside('[role="slider"], [aria-label="滑块"]').filter(visible).length,
  settledFrames: inside('iframe').length,
  settledMaskChildren: roots.reduce((n, root) => n + root.children.length, 0)
}), 3000));
"""


def _access_diagnostics(driver: webdriver.Remote) -> dict[str, int]:
    """Summarize passive browser evidence locally; raw logs never leave the Pi."""
    counts: dict[str, int] = {}
    try:
        ui = driver.execute_script(ACCESS_DIAGNOSTIC_JS)
        if isinstance(ui, dict):
            for key in (
                "documentHidden",
                "documentFocused",
                "appRootPresent",
                "vueRootPresent",
                "scriptReferences",
                "maskRoots",
                "maskChildren",
                "semanticHandles",
                "legacyHandles",
                "frames",
                "accessibleFrames",
                "verificationScripts",
                "settledLegacyHandles",
                "settledSemanticHandles",
                "settledFrames",
                "settledMaskChildren",
            ):
                if type(ui.get(key)) is int and 0 <= ui[key] <= 10000:
                    counts[key] = ui[key]
    except Exception:
        pass

    def increment(key: str) -> None:
        counts[key] = min(counts.get(key, 0) + 1, 10000)

    try:
        # Generic Remote has no Chromium get_log helper in Selenium 4.46.
        # Use the same wire command as ChromiumDriver, without changing sessions.
        events = driver.execute("getLog", {"type": "performance"})["value"]
        counts["performanceLogEntries"] = min(len(events), 10000)
        requests: dict[str, str] = {}
        hosts: dict[str, str] = {}
        for entry in events:
            message = json.loads(entry["message"])["message"]
            params = message.get("params", {})
            method = message.get("method")
            if method == "Network.requestWillBeSent":
                path = urlparse(params.get("request", {}).get("url", "")).path
                requests[params.get("requestId", "")] = (
                    "order" if path.endswith("/getVenueOrderList") else "other"
                )
                host = urlparse(params.get("request", {}).get("url", "")).hostname or ""
                hosts[params.get("requestId", "")] = (
                    "aliyunCdnFailures"
                    if host == "alicdn.com" or host.endswith(".alicdn.com")
                    else "ydmapFailures"
                    if host == "ydmap.cn" or host.endswith(".ydmap.cn")
                    else "otherHostFailures"
                )
            elif method == "Network.responseReceived":
                response = params.get("response", {})
                path = urlparse(response.get("url", "")).path
                mime = response.get("mimeType", "")
                status = response.get("status", 0)
                if isinstance(status, int | float) and status >= 400:
                    increment("httpErrors")
                    if params.get("type") == "Document":
                        increment("documentHttpErrors")
                    if path.endswith("/favicon.ico"):
                        increment("faviconHttpErrors")
                endpoint = path.rsplit("/", 1)[-1]
                api = {
                    "getSalesItemList": "catalog",
                    "getVenueCalendarList": "calendar",
                    "getSportVenueConfig": "config",
                }.get(endpoint)
                if api:
                    increment(
                        api
                        + (
                            "HtmlResponses"
                            if mime == "text/html"
                            else "JsonResponses"
                            if "json" in mime
                            else "OtherResponses"
                        )
                    )
                if path.endswith("/getVenueOrderList"):
                    increment(
                        "orderHtmlResponses"
                        if mime == "text/html"
                        else "orderJsonResponses"
                        if "json" in mime
                        else "orderOtherResponses"
                    )
                    status = response.get("status")
                    if type(status) is int and 100 <= status <= 599:
                        counts["lastOrderStatus"] = status
                if params.get("type") == "Script":
                    increment("scriptResponses")
                    if mime == "text/html":
                        increment("scriptHtmlResponses")
                    if response.get("status", 0) >= 400:
                        increment("scriptHttpErrors")
            elif method == "Network.loadingFailed":
                increment(hosts.get(params.get("requestId", ""), "otherHostFailures"))
                increment(
                    "orderFailures"
                    if requests.get(params.get("requestId")) == "order"
                    else "scriptFailures"
                    if params.get("type") == "Script"
                    else "otherFailures"
                )
                error = params.get("errorText", "")
                if "CERT" in error or "SSL" in error:
                    increment("tlsFailures")
                elif "NAME_NOT_RESOLVED" in error:
                    increment("dnsFailures")
                if params.get("blockedReason"):
                    increment("blockedFailures")
    except Exception:
        counts["performanceLogUnavailable"] = 1
    try:
        browser_events = driver.execute("getLog", {"type": "browser"})["value"]
        counts["browserLogEntries"] = min(len(browser_events), 10000)
        for entry in browser_events:
            message = entry.get("message", "")
            if "Content Security Policy" in message or "Content-Security-Policy" in message:
                increment("cspErrors")
            if "ReferenceError" in message:
                increment("referenceErrors")
            if "TypeError" in message:
                increment("typeErrors")
            if "SyntaxError" in message:
                increment("syntaxErrors")
            if "MIME type" in message:
                increment("mimeTypeErrors")
            http_error = re.search(r"status of (401|403|404|429|500|502|503)\b", message)
            if http_error:
                increment("consoleHttp" + http_error[1] + "Errors")
            if "ERR_CERT" in message or "ERR_SSL" in message:
                increment("consoleTlsErrors")
            if "ERR_NAME_NOT_RESOLVED" in message:
                increment("consoleDnsErrors")
            if "unsafe-eval" in message:
                increment("evalBlockedErrors")
            if "Failed to load resource" in message:
                increment("resourceLoadErrors")
    except Exception:
        counts["browserLogUnavailable"] = 1
    return counts


def _normal_verification_once(driver: webdriver.Remote, state: dict[str, Any]) -> bool:
    control = driver.execute_script(VERIFICATION_CONTROL_JS)
    status = control.get("status") if isinstance(control, dict) else None
    state["control"] = (
        status
        if status
        in (
            "wrong_host",
            "root_missing",
            "controls_missing",
            "ambiguous_controls",
            "instruction_unrecognized",
            "geometry_invalid",
            "control_obstructed",
            "ready",
        )
        else "probe_failed"
    )
    if not isinstance(control, dict) or status != "ready" or "handle" not in control:
        state["outcome"] = "unsupported_control"
        return False
    distance = control.get("distance")
    if type(distance) is not int or not 50 <= distance <= 600:
        state["outcome"] = "unsupported_control"
        return False
    from selenium.webdriver.common.action_chains import ActionChains

    # A single ordinary pointer drag, explicitly authorized by the operator.
    # No retry, evasive trajectory, event injection or provider API invocation.
    state.update(attempted=True, outcome="not_passed")
    ActionChains(driver, duration=1000).click_and_hold(control["handle"]).move_by_offset(
        distance, 0
    ).release().perform()
    return True


def _prefixed_court_name(label: str, court: str) -> str:
    """Disambiguate courts whose raw name omits its venue group."""
    name = str(court).strip()
    if not label or not name or label in name:
        return name
    return f"{label}{name}"


def _browser_environment(driver: webdriver.Remote) -> dict[str, Any]:
    capabilities = getattr(driver, "capabilities", {})
    if not isinstance(capabilities, dict):
        return {}
    browser = capabilities.get("browserVersion")
    if not isinstance(browser, str) or not re.fullmatch(r"\d{1,4}(?:\.\d{1,6}){1,3}", browser):
        return {}
    result: dict[str, Any] = {
        "browserVersion": browser,
        "userAgentOverrideEnabled": False,
        "profileResetBeforeScrape": False,
    }
    chrome = capabilities.get("chrome")
    driver_value = chrome.get("chromedriverVersion") if isinstance(chrome, dict) else None
    if isinstance(driver_value, str):
        version = driver_value.split(" ", 1)[0]
        if re.fullmatch(r"\d{1,4}(?:\.\d{1,6}){1,3}", version):
            result["driverVersion"] = version
            result["driverMajorMatchesBrowser"] = version.split(".")[0] == browser.split(".")[0]
    return result


def _capture_failure_ui(driver: webdriver.Remote, venue: str) -> dict[str, Any] | None:
    """Explicit manual preflight only; capture our public page, never credentials."""
    if os.environ.get("YDMAP_CAPTURE_BROWSER_UI") != "1":
        return None
    config = getattr(driver, "_ydmap_client_config", None)
    previous = getattr(config, "timeout", None)
    try:
        if config is not None:
            config.timeout = DRIVER_CLEANUP_TIMEOUT
        sensitive = driver.execute_script(r"""
const text = document.body?.innerText || '';
return /[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}/i.test(text) ||
  /\b1[3-9]\d{9}\b/.test(text) ||
  /\b(?:\d{1,3}\.){3}\d{1,3}\b/.test(text) ||
  /(?:[0-9a-f]{0,4}:){3,7}[0-9a-f]{0,4}|\b[0-9a-f]{1,4}::[0-9a-f]+\b/i.test(text) ||
  /扫码登录|扫码授权|扫描二维码.{0,12}登录|scan.{0,20}(?:login|log in|sign in)/i.test(text) ||
  [...document.querySelectorAll('input[type=email],input[type=password],input[type=tel]')]
    .some(input => !!input.value);
""")
        if sensitive is not False:
            return None
        png = driver.get_screenshot_as_png()
        if not isinstance(png, bytes) or not 24 <= len(png) <= UI_CAPTURE_MAX_BYTES:
            return None
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            return None
        encoded = base64.b64encode(png).decode("ascii")
        return {
            "venue": venue,
            "mime_type": "image/png",
            "sha256": hashlib.sha256(png).hexdigest(),
            "chunks": [encoded[offset : offset + 4096] for offset in range(0, len(encoded), 4096)],
        }
    except Exception:
        return None
    finally:
        if config is not None:
            config.timeout = previous


def _stop_with_error(
    *,
    error: str,
    venue: str,
    payload: dict[str, Any] | None = None,
    captcha: bool = False,
) -> dict[str, Any]:
    observed = payload or {}
    result = {
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
                "challengeText",
                "challengeMaskVisible",
                "documentComplete",
                "scheduleComponentPresent",
                "failurePhase",
                "requestedProduct",
                "accessDiagnostics",
            )
            if key in observed
        },
    }
    if isinstance(observed.get("diagnostic_ui"), dict):
        result["diagnostic_ui"] = observed["diagnostic_ui"]
    return result


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


def _scrape_available_slots(
    venue: str,
    days: int,
    *,
    source_evidence: bool,
    verification: dict[str, Any] | None = None,
    runtime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    groups = VENUE_GROUPS.get(venue)
    if not groups:
        return _stop_with_error(error=f"unknown_venue:{venue}", venue=venue)
    if (
        source_evidence
        and venue == "baoti"
        and os.environ.get("YDMAP_DIAGNOSTIC_FIRST_PRODUCT") == "windrain"
    ):
        groups = tuple(sorted(groups, key=lambda group: group[0] != "windrain"))
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
    source_budget: dict[str, Any] = {"remaining": SOURCE_TOTAL_BYTES, "seen": set()}
    phase = "browser_start"
    requested_product = parse_qs(urlparse(groups[0][2]).query)["salesItemId"][0]
    # A larger local wire timeout must never extend the complete scrape budget.
    # Kill only this scrape's current driver if a renderer stops answering;
    # the reserved thirty seconds remain available for browser cleanup.
    watchdog = threading.Timer(
        max(0, deadline - time.monotonic()),
        lambda: _stop_driver_service(getattr(driver, "_ydmap_service", None)),
    )
    watchdog.daemon = True
    watchdog.start()
    try:
        next_product_at = 0.0
        for index, (key, label, url) in enumerate(groups):
            requested_product = parse_qs(urlparse(url).query)["salesItemId"][0]
            if proc is not None:
                _stop(proc, driver)
                proc = None
                driver = None
            phase = "browser_start"
            if index > 0 and venue == "baoti":
                delay = next_product_at - time.monotonic()
                if delay > 0:
                    time.sleep(_remaining(deadline, delay))
            _remaining(deadline, 20)
            # A fixed private profile belongs to this product across polls.
            # Each source opens its supported URL natively, like Dashah;
            # no cross-product browser/app state or product-tab click is reused.
            profile = PROFILE / f"{venue}-{key or 'main'}"
            _cleanup_stale_browser(profile)
            proc = _start_chromium(url, profile=profile)
            _wait_devtools(timeout=_remaining(deadline, 40))
            time.sleep(_remaining(deadline, 4))
            phase = "browser_attach"
            driver = _attach(timeout=_remaining(deadline, 30))
            if runtime is not None:
                runtime.update(_browser_environment(driver))
            parsed = urlparse(url)
            identity: VenueIdentity = {
                "host": parsed.hostname or "",
                "sales_id": parsed.path.rsplit("/", 1)[-1],
                "sales_item_id": parse_qs(parsed.query)["salesItemId"][0],
                "label": label,
            }
            phase = "initial_schedule" if index == 0 else "product_navigation"
            payload = _wait_for_schedule(
                driver,
                deadline=deadline,
                verification=verification,
                phase=phase,
                **identity,
            )
            if not payload.get("ready"):
                if source_evidence and payload.get("captcha") is True:
                    payload["diagnostic_ui"] = _capture_failure_ui(driver, venue)
                return _stop_with_error(
                    error=payload.get("error") or "schedule_not_ready",
                    venue=venue,
                    payload=payload,
                    captcha=bool(payload.get("captcha")),
                )
            initial_issue = _snapshot_issue(payload, **identity)
            if initial_issue:
                return _stop_with_error(error=initial_issue, venue=venue, payload=payload)
            # Calendar verification followed the third rapid product activation
            # with either product order. Pace fresh product loads, not DAG runs
            # or retries. Count from readiness so startup latency cannot shorten it.
            next_product_at = time.monotonic() + BAOTI_PRODUCT_INTERVAL_SECONDS
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
                phase = "date_selection"
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
                phase = "refreshed_schedule"
                payload = _wait_for_schedule(
                    driver,
                    timeout=25,
                    deadline=deadline,
                    expected_date=booking_iso,
                    previous=previous,
                    verification=verification,
                    phase=phase,
                    **identity,
                )
                if not payload.get("ready"):
                    if source_evidence and payload.get("captcha") is True:
                        payload["diagnostic_ui"] = _capture_failure_ui(driver, venue)
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
                if source_evidence:
                    phase = "source_evidence"
                    _remaining(deadline, 10)
                    payload = _extract_day(driver, source_evidence=True)
                    issue = _snapshot_issue(
                        payload, expected_date=booking_iso, previous=previous, **identity
                    )
                    if issue:
                        return _stop_with_error(
                            error=issue,
                            venue=venue,
                            payload=payload,
                            captcha=bool(payload.get("captcha")),
                        )
                    if not isinstance(payload.get("sourceEvidence"), dict):
                        return _stop_with_error(
                            error="source_identity_unavailable", venue=venue, payload=payload
                        )
                bucket = collected.setdefault(booking_iso, {})
                known = court_names.setdefault(booking_iso, [])
                group_names = [_prefixed_court_name(label, name) for name in payload["courtNames"]]
                for name in group_names:
                    if name not in known:
                        known.append(name)
                for court, ranges in payload["courts"].items():
                    name = _prefixed_court_name(label, str(court))
                    bucket[name] = ranges
                group = {
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
                if source_evidence:
                    group["source_evidence"] = _source_evidence(
                        payload["sourceEvidence"], label, source_budget
                    )
                evidence.setdefault(booking_iso, []).append(group)
        return {
            "schema_version": SCHEMA_VERSION,
            "ok": True,
            "captcha": False,
            "venue": venue,
            "venue_name": VENUE_NAMES.get(venue, venue),
            "days": _days_payload(collected, court_names, evidence),
        }
    except Exception as exc:
        error = type(exc).__name__
        # Only our fixed JS sentinel codes may cross the browser exception boundary.
        # Never publish Selenium messages, stacks, URLs or page content.
        if error == "JavascriptException":
            for code in (
                "bookability_predicate_unavailable",
                "bookability_predicate_invalid",
                "bookability_product_type_unverified",
            ):
                if code in str(exc):
                    error = code
                    break
        observed: dict[str, Any] = {"failurePhase": phase, "requestedProduct": requested_product}
        if driver is not None and error in {
            "ReadTimeoutError",
            "MaxRetryError",
            "ProtocolError",
            "TimeoutException",
            "WebDriverException",
        }:
            # Passive local logs/UI only; do not repeat the failed source request
            # or interaction. Limit each diagnostic command and total lifetime.
            config = getattr(driver, "_ydmap_client_config", None)
            if config is not None:
                config.timeout = DRIVER_CLEANUP_TIMEOUT
            observed["accessDiagnostics"] = _access_diagnostics(driver)
        return _stop_with_error(error=error, venue=venue, payload=observed)
    finally:
        watchdog.cancel()
        if proc is not None:
            _stop(proc, driver)


def scrape_available_slots(
    venue: str = DEFAULT_VENUE,
    days: int = DEFAULT_DAYS,
    *,
    source_evidence: bool = False,
    verification_once: bool = False,
) -> dict[str, Any]:
    global VERIFICATION_AVAILABLE
    verification = None
    if verification_once and VERIFICATION_AVAILABLE and source_evidence and venue == "baoti":
        VERIFICATION_AVAILABLE = False
        verification = {"attempted": False, "outcome": "not_needed"}
    runtime: dict[str, Any] = {}
    result = _scrape_available_slots(
        venue, days, source_evidence=source_evidence, verification=verification, runtime=runtime
    )
    if runtime:
        result.setdefault("diagnostics", {}).update(runtime)
    if verification is not None:
        result.setdefault("diagnostics", {}).update(
            verificationAttempted=verification["attempted"],
            verificationOutcome=verification["outcome"],
        )
        if "control" in verification:
            result["diagnostics"]["verificationControl"] = verification["control"]
    return result


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
            requested_evidence = query.get("evidence") == ["source-v1"]
            payload = scrape_available_slots(
                venue,
                days,
                source_evidence=requested_evidence,
                verification_once=query.get("verification") == ["once"],
            )
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
