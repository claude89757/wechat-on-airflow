#!/usr/bin/env python3
"""Local Chromium scrape service for Dashah International Tennis Center."""

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

BOOKING_URL = "https://wxsports.ydmap.cn/booking/schedule/100220?salesItemId=100000"
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
SCRAPE_LOCK = threading.Lock()

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


def _start_chromium() -> subprocess.Popen[Any]:
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
        BOOKING_URL,
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


def scrape_available_slots(days: int = DEFAULT_DAYS) -> dict[str, Any]:
    days = min(max(days, 1), 7)
    _cleanup_stale_browser()
    proc = _start_chromium()
    driver = None
    try:
        _wait_devtools()
        time.sleep(4)
        driver = _attach()
        payload = _wait_for_schedule(driver)
        if payload.get("captcha"):
            return {"ok": False, "captcha": True, "error": "captcha", "days": []}
        if not payload.get("ready"):
            return {"ok": False, "captcha": False, "error": "schedule_not_ready", "days": []}
        today = date.today()
        collected: list[dict[str, Any]] = []
        previous_signature = str(payload.get("signature") or "")
        for offset in range(days):
            booking_date = today + timedelta(days=offset)
            label = booking_date.strftime("%m-%d")
            if offset > 0:
                clicked = driver.execute_script(CLICK_DATE_JS, label)
                if not clicked:
                    return {
                        "ok": False,
                        "captcha": False,
                        "error": f"date_tab_not_found:{label}",
                        "days": collected,
                    }
                payload = _wait_for_schedule(
                    driver,
                    timeout=25,
                    previous_signature=previous_signature,
                )
                if payload.get("captcha"):
                    return {"ok": False, "captcha": True, "error": "captcha", "days": collected}
                if not payload.get("ready"):
                    return {
                        "ok": False,
                        "captcha": False,
                        "error": "schedule_not_ready",
                        "days": collected,
                    }
            courts = payload.get("courts") or {}
            previous_signature = str(payload.get("signature") or previous_signature)
            collected.append(
                {
                    "date": booking_date.isoformat(),
                    "courts": courts,
                    "court_names": payload.get("courtNames") or [],
                }
            )
        return {
            "ok": True,
            "captcha": False,
            "venue_name": "大沙河国际网球交流中心",
            "days": collected,
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
            self._send_json(200, {"ok": True, "service": "dsh_ydmap"})
            return
        if parsed.path != "/inspect":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        query = parse_qs(parsed.query)
        try:
            days = int((query.get("days") or [str(DEFAULT_DAYS)])[0])
        except ValueError:
            days = DEFAULT_DAYS
        if not SCRAPE_LOCK.acquire(blocking=False):
            self._send_json(429, {"ok": False, "error": "busy"})
            return
        try:
            payload = scrape_available_slots(days)
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
