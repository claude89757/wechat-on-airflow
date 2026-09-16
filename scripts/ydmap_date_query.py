#!/usr/bin/env python3
"""One bounded normal date-switch probe; never clicks slots or publishes observations."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from ydmap_query_evidence import QueryTrace
from ydmap_source_compare import PUBLIC_JS, SOURCES, health, source_matches


def snapshot(driver: Any, source: str) -> dict[str, Any]:
    page = driver.execute_script(PUBLIC_JS)
    return {
        "sourceMatches": source_matches(page.get("url", ""), source),
        **{
            k: page.get(k)
            for k in (
                "selectedDate",
                "selectedProduct",
                "tableFound",
                "classes",
                "courts",
                "challenge",
                "loginRequired",
                "visibleVerifications",
            )
        },
    }


def blocked(page: dict[str, Any], trace: QueryTrace | None = None) -> bool:
    return bool(
        page.get("challenge")
        or page.get("loginRequired")
        or page.get("visibleVerifications")
        or (trace and any(q.get("accessChallenge") for q in trace.results))
    )


def observe(source: str) -> dict[str, Any]:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By

    host, venue, product = SOURCES[source]
    report: dict[str, Any] = {
        "source": source,
        "dateClicks": 0,
        "bookabilityVerified": False,
        "queries": [],
    }
    proc = driver = trace = None
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ydmap-date-query-") as profile:
        try:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            if port == 9224:
                raise RuntimeError("reserved_port")
            env = os.environ.copy()
            env.setdefault("DISPLAY", ":0")
            env.setdefault("XAUTHORITY", str(Path.home() / ".Xauthority"))
            env.update(LANG="zh_CN.UTF-8", LANGUAGE="zh_CN:zh", LC_ALL="zh_CN.UTF-8")
            proc = subprocess.Popen(
                [
                    "/usr/lib/chromium/chromium",
                    f"--user-data-dir={profile}",
                    f"--remote-debugging-port={port}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-dev-shm-usage",
                    "--disable-extensions",
                    "--disable-sync",
                    "--lang=zh-CN",
                    "--accept-lang=zh-CN,zh,en-US,en",
                    "--window-size=1280,800",
                    "--window-position=80,40",
                    f"https://{host}/booking/schedule/{venue}?salesItemId={product}",
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            deadline = time.monotonic() + 15
            while True:
                try:
                    with opener.open(
                        f"http://127.0.0.1:{port}/json/version", timeout=1
                    ) as response:
                        json.loads(response.read(4096))
                    break
                except Exception:
                    if time.monotonic() >= deadline or proc.poll() is not None:
                        raise RuntimeError("browser_start_failed") from None
                    time.sleep(0.25)
            time.sleep(4)
            options = Options()
            options.debugger_address = f"127.0.0.1:{port}"
            driver = webdriver.Chrome(
                service=Service(shutil.which("chromedriver") or "/usr/local/bin/chromedriver"),
                options=options,
            )
            driver.set_script_timeout(5)
            page = snapshot(driver, source)
            report["initial"] = page
            if blocked(page) or not page["sourceMatches"]:
                report["state"] = "verification_required" if blocked(page) else "source_mismatch"
                return report
            with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                pages = json.load(response)
            target = next(
                p
                for p in pages
                if p.get("type") == "page" and source_matches(p.get("url", ""), source)
            )
            trace = QueryTrace(target["webSocketDebuggerUrl"], host)
            deadline = time.monotonic() + 30
            click_after = time.monotonic() + 6
            while time.monotonic() < deadline:
                trace.drain()
                page = snapshot(driver, source)
                if blocked(page, trace) or not page["sourceMatches"]:
                    break
                if (
                    not report["dateClicks"]
                    and time.monotonic() >= click_after
                    and page.get("selectedDate")
                ):
                    tomorrow = date.fromisoformat(page["selectedDate"]) + timedelta(days=1)
                    label = tomorrow.strftime("%m-%d")
                    elements = driver.find_elements(
                        By.XPATH, f"//*[not(*) and normalize-space(.)='{label}']"
                    )
                    visible = [e for e in elements if e.is_displayed() and e.is_enabled()]
                    if visible:
                        report["requestedDate"] = tomorrow.isoformat()
                        visible[0].click()
                        report["dateClicks"] = 1
                time.sleep(0.5)
            trace.drain()
            report["final"] = page
            report["queries"] = trace.results
            report["state"] = (
                "verification_required"
                if blocked(page, trace)
                else "source_mismatch"
                if not page["sourceMatches"]
                else "evidence_collected_not_acceptance"
            )
        except Exception as error:
            report.update(state="probe_failed", errorClass=type(error).__name__)
        finally:
            report["elapsedSeconds"] = round(time.monotonic() - started, 2)
            if trace:
                try:
                    trace.close()
                except Exception:
                    report["traceCleanupUnconfirmed"] = True
            if driver:
                try:
                    driver.quit()
                except Exception:
                    report["driverCleanupUnconfirmed"] = True
            if proc and proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait(timeout=5)
    return report


def main() -> None:
    report: dict[str, Any] = {
        "mode": "normal_date_switch_evidence",
        "observedAt": datetime.now(UTC).isoformat(),
        "productionChanged": False,
        "productionReady": False,
        "externalTestSends": 0,
        "healthBefore": health(),
        "sources": [],
    }
    for source in SOURCES:
        result = observe(source)
        report["sources"].append(result)
        if result["state"] == "verification_required":
            break
    report["healthAfter"] = health()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
