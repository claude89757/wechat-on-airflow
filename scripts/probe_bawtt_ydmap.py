#!/usr/bin/env python3
"""Inspect two public BAWTT pages without booking, credentials, or notifications.

This deliberately reports page structure, not bookable slots. A visible grid is
not evidence that a cell is released or that the selected booking date is fresh.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

TARGETS = {
    "bawtt_104036_indoor": "111317",
    "bawtt_104036_outdoor": "103224",
}
ORIGIN = "https://bawtt.ydmap.cn"
BOOKING_PATH = "/booking/schedule/104036"

# Reuse the existing Dashah scraper's Vue ScheduleTable discovery, but do NOT
# reuse its absence-of-disabled-class test as a bookability decision.
INSPECT_JS = r"""
const text = document.body ? document.body.innerText : '';
const challenge = /Access Verification|slide to verify|人机验证|滑动验证|安全验证/i.test(text);
const root = document.querySelector('#app');
const seen = new Set();
function find(vm) {
  if (!vm || seen.has(vm)) return null;
  seen.add(vm);
  const opts = vm.$options || {};
  if ((opts.name || opts._componentTag) === 'ScheduleTable') return vm;
  for (const child of vm.$children || []) {
    const found = find(child);
    if (found) return found;
  }
  return null;
}
const table = find(root && root.__vue__);
let cells = 0;
let cellsWithCourt = 0;
let cellsWithExplicitClass = 0;
const fieldNames = new Set();
const classCounts = {};
const rows = table && Array.isArray(table.rows) ? table.rows : [];
for (const row of rows) {
  for (const col of Array.isArray(row) ? row : Object.values(row || {})) {
    if (!col || !col.startTimeText || !col.endTimeText) continue;
    cells++;
    if (col.platformInfo && col.platformInfo.venueName) cellsWithCourt++;
    for (const key of Object.keys(col)) fieldNames.add(key);
    const cls = typeof col.className === 'string' ? col.className.trim() : '';
    if (cls) cellsWithExplicitClass++;
    // Only expose known structural status tokens, never arbitrary page content.
    for (const token of ['completed','locked','scheduled','disabled','expired','not-open']) {
      if (cls.toLowerCase().includes(token)) classCounts[token] = (classCounts[token] || 0) + 1;
    }
  }
}
return {challenge, tableFound: Boolean(table), cells, cellsWithCourt,
  cellsWithExplicitClass, classCounts, fieldNames: [...fieldNames].sort()};
"""


def booking_url(target: str) -> str:
    if target not in TARGETS:
        raise ValueError("unsupported_target")
    return f"{ORIGIN}{BOOKING_PATH}?salesItemId={TARGETS[target]}"


def source_matches(url: str, target: str) -> bool:
    if target not in TARGETS:
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.netloc == "bawtt.ydmap.cn"
            and parsed.path == BOOKING_PATH
            and parse_qs(parsed.query).get("salesItemId") == [TARGETS[target]]
        )
    except ValueError:
        return False


def summarize(target: str, url: str, payload: object) -> dict[str, Any]:
    result: dict[str, Any] = {
        "target": target,
        "salesItemId": TARGETS[target],
        "sourceMatches": source_matches(url, target),
        "structureReady": False,
        "productionReady": False,
    }
    if not isinstance(payload, dict):
        result["reason"] = "invalid_browser_payload"
        return result
    if payload.get("challenge") is True:
        result["reason"] = "access_verification_required"
        return result
    if not result["sourceMatches"]:
        result["reason"] = "unexpected_redirect_or_source"
        return result
    for key in ("cells", "cellsWithCourt", "cellsWithExplicitClass"):
        value = payload.get(key)
        result[key] = value if type(value) is int and value >= 0 else 0
    result["tableFound"] = payload.get("tableFound") is True
    result["structureReady"] = result["tableFound"] and result["cells"] > 0
    result["reason"] = (
        "structure_observed_requires_live_bookability_validation"
        if result["structureReady"]
        else "schedule_table_not_observed"
    )
    fields = payload.get("fieldNames")
    result["fieldNames"] = (
        sorted({item for item in fields if isinstance(item, str) and item.isidentifier()})[:100]
        if isinstance(fields, list)
        else []
    )
    counts = payload.get("classCounts")
    result["classCounts"] = {
        key: counts[key]
        for key in ("completed", "locked", "scheduled", "disabled", "expired", "not-open")
        if isinstance(counts, dict) and type(counts.get(key)) is int and counts[key] >= 0
    }
    return result


def probe_target(target: str, timeout: float = 45.0) -> dict[str, Any]:
    """Use an isolated browser; never attach to/kill the production browser."""
    driver = None
    started = time.monotonic()
    result: dict[str, Any] = {
        "target": target,
        "salesItemId": TARGETS[target],
        "structureReady": False,
        "productionReady": False,
    }
    with tempfile.TemporaryDirectory(prefix="bawtt-readonly-") as profile:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            options = Options()
            for arg in (
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,800",
                f"--user-data-dir={profile}",
            ):
                options.add_argument(arg)
            chrome = shutil.which("google-chrome") or shutil.which("chromium")
            if chrome:
                options.binary_location = chrome
            binary = shutil.which("chromedriver")
            service = Service(binary) if binary else Service()
            driver = webdriver.Chrome(options=options, service=service)
            driver.set_page_load_timeout(timeout)
            driver.set_script_timeout(10)
            driver.get(booking_url(target))
            deadline = time.monotonic() + timeout
            while True:
                result = summarize(target, driver.current_url, driver.execute_script(INSPECT_JS))
                if result["structureReady"] or result["reason"] in (
                    "access_verification_required",
                    "unexpected_redirect_or_source",
                ):
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(1)
        except Exception as exc:
            # Exception strings may contain HTML, request headers, or session IDs.
            result["errorClass"] = type(exc).__name__
            result["reason"] = "browser_probe_failed"
        finally:
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    result["cleanupError"] = True
    result["elapsedSeconds"] = round(time.monotonic() - started, 2)
    return result


def main() -> int:
    targets = [probe_target(target) for target in TARGETS]
    report = {
        "mode": "read_only_public_page_probe",
        "observedAt": datetime.now(UTC).isoformat(),
        "productionChanged": False,
        "externalTestSends": 0,
        "productionReady": False,
        "targets": targets,
    }
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if all(item["structureReady"] for item in targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
