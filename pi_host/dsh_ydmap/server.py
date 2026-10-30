#!/usr/bin/env python3
"""Local Chromium scrape service for the YDMap tennis venues."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

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
LISTEN_PORT = 8788
PROFILE = Path("/tmp/dsh_ydmap_profile")
DEBUG_PORT = 9224
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

CLICK_DATE_JS = """
const target = arguments[0];
const nodes = [...document.querySelectorAll('div,span,button,li,a')];
const matches = nodes.filter((el) => {
  const text = (el.innerText || '').trim().split('\\n')[0];
  return text === target && el.offsetParent !== null;
}).map((el) => {
  const box = el.getBoundingClientRect();
  return { el, children: el.children.length, area: box.width * box.height };
});
if (!matches.length) return false;
matches.sort((left, right) => {
  if (left.children !== right.children) return left.children - right.children;
  return right.area - left.area;
});
matches[0].el.click();
return true;
"""

EXTRACT_DAY_JS = r"""
const bodyText = document.body && document.body.innerText || '';
const captcha = /Access Verification|slide to verify/.test(bodyText);
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
    if (/completed|locked|scheduled|disabled|expired|not-open/i.test(cls)) return;
    const ranges = courts[venue] || [];
    if (!ranges.some((item) => item[0] === col.startTimeText && item[1] === col.endTimeText)) {
      ranges.push([col.startTimeText, col.endTimeText]);
    }
    courts[venue] = ranges;
  });
});
return {
  captcha,
  ready: cellCount > 0,
  signature: `${cellCount}:${Object.keys(courts).sort().join(',')}:${JSON.stringify(courts)}`,
  courts,
  courtNames,
  cellCount,
};
"""


def _cleanup_stale_browser() -> None:
    subprocess.run(
        ["pkill", "-f", f"remote-debugging-port={DEBUG_PORT}"],
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


def _wait_devtools(timeout: int = 40) -> None:
    url = f"http://127.0.0.1:{DEBUG_PORT}/json/version"
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                json.loads(resp.read().decode())
                return
        except Exception as exc:
            last = str(exc)
            time.sleep(0.4)
    raise RuntimeError(f"devtools not ready: {last}")


def _attach() -> webdriver.Chrome:
    opts = Options()
    opts.debugger_address = f"127.0.0.1:{DEBUG_PORT}"
    return webdriver.Chrome(service=Service(CHROMEDRIVER), options=opts)


def _stop(proc: subprocess.Popen[Any], driver: webdriver.Chrome | None) -> None:
    if driver is not None:
        try:
            driver.quit()
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


def _extract_day(driver: webdriver.Chrome) -> dict[str, Any]:
    payload = driver.execute_script(EXTRACT_DAY_JS)
    return payload if isinstance(payload, dict) else {}


def _wait_for_schedule(
    driver: webdriver.Chrome,
    timeout: int = 45,
    *,
    previous_signature: str | None = None,
) -> dict[str, Any]:
    deadline = time.time() + timeout
    last: dict[str, Any] = {}
    while time.time() < deadline:
        last = _extract_day(driver)
        if last.get("captcha"):
            return last
        if last.get("ready") and last.get("signature") != previous_signature:
            return last
        time.sleep(1.5)
    return last


def _prefixed_court_name(label: str, court: str) -> str:
    """Disambiguate courts whose raw name omits its venue group."""
    name = str(court).strip()
    if not label or not name or label in name:
        return name
    return f"{label}{name}"


def _stop_with_error(
    *,
    error: str,
    days: dict[str, dict[str, list[list[str]]]],
    names: dict[str, list[str]],
    captcha: bool = False,
) -> dict[str, Any]:
    return {
        "ok": False,
        "captcha": captcha,
        "error": error,
        "days": _days_payload(days, names),
    }


def _days_payload(
    days: dict[str, dict[str, list[list[str]]]],
    names: dict[str, list[str]],
) -> list[dict[str, Any]]:
    return [
        {
            "date": booking_date,
            "courts": days[booking_date],
            "court_names": names.get(booking_date) or [],
        }
        for booking_date in sorted(days)
    ]


def scrape_available_slots(venue: str = DEFAULT_VENUE, days: int = DEFAULT_DAYS) -> dict[str, Any]:
    groups = VENUE_GROUPS.get(venue)
    if not groups:
        return {"ok": False, "captcha": False, "error": f"unknown_venue:{venue}", "days": []}
    days = min(max(days, 1), 7)
    _cleanup_stale_browser()
    proc = _start_chromium(groups[0][2])
    driver = None
    collected: dict[str, dict[str, list[list[str]]]] = {}
    court_names: dict[str, list[str]] = {}
    try:
        _wait_devtools()
        time.sleep(4)
        driver = _attach()
        for index, (_key, label, url) in enumerate(groups):
            if index > 0:
                driver.get(url)
                time.sleep(3)
            payload = _wait_for_schedule(driver)
            if payload.get("captcha"):
                return _stop_with_error(
                    error="captcha", days=collected, names=court_names, captcha=True
                )
            if not payload.get("ready"):
                return _stop_with_error(
                    error="schedule_not_ready", days=collected, names=court_names
                )
            previous_signature = str(payload.get("signature") or "")
            for offset in range(days):
                booking_date = date.today() + timedelta(days=offset)
                label_md = booking_date.strftime("%m-%d")
                if offset > 0:
                    clicked = driver.execute_script(CLICK_DATE_JS, label_md)
                    if not clicked:
                        return _stop_with_error(
                            error=f"date_tab_not_found:{label_md}",
                            days=collected,
                            names=court_names,
                        )
                    payload = _wait_for_schedule(
                        driver, timeout=25, previous_signature=previous_signature
                    )
                    if payload.get("captcha"):
                        return _stop_with_error(
                            error="captcha",
                            days=collected,
                            names=court_names,
                            captcha=True,
                        )
                    if not payload.get("ready"):
                        return _stop_with_error(
                            error="schedule_not_ready", days=collected, names=court_names
                        )
                booking_iso = booking_date.isoformat()
                bucket = collected.setdefault(booking_iso, {})
                known = court_names.setdefault(booking_iso, [])
                for court, ranges in (payload.get("courts") or {}).items():
                    name = _prefixed_court_name(label, str(court))
                    if not name:
                        continue
                    bucket.setdefault(name, []).extend(ranges)
                    if name not in known:
                        known.append(name)
                previous_signature = str(payload.get("signature") or previous_signature)
        return {
            "ok": True,
            "captcha": False,
            "venue": venue,
            "venue_name": VENUE_NAMES.get(venue, venue),
            "days": _days_payload(collected, court_names),
        }
    finally:
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
                    "venues": sorted(VENUE_GROUPS),
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
            self._send_json(429, {"ok": False, "error": "busy"})
            return
        try:
            payload = scrape_available_slots(venue, days)
            self._send_json(200 if payload.get("ok") else 503, payload)
        except Exception as exc:
            self._send_json(500, {"ok": False, "error": type(exc).__name__})
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
