#!/usr/bin/env python3
"""One ordinary-browser, isolated-profile visit per source; no availability writes."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from bawtt_live_query import read_queries

SOURCES = {
    "dashah_control": ("wxsports.ydmap.cn", "100220", "100000"),
    "indoor": ("bawtt.ydmap.cn", "104036", "111317"),
    "outdoor": ("bawtt.ydmap.cn", "104036", "103224"),
}
PUBLIC_JS = r"""
const root = document.querySelector('#app'), text = document.body?.innerText || '';
const seen = new Set(), components = []; let table = null, layout = null;
function visit(vm, depth) {
  if (!vm || seen.has(vm) || depth > 7 || components.length >= 35) return;
  seen.add(vm); const o=vm.$options||{}, name=o.name||o._componentTag||'anonymous';
  components.push(name); if(name==='ScheduleTable') table=vm; if(name==='Layout') layout=vm;
  for(const child of vm.$children||[]) visit(child,depth+1);
}
visit(root?.__vue__,0);
const classes={}, courts=new Set(), cells=[];
for(const row of table?.rows||[]) for(const c of Array.isArray(row)?row:Object.values(row||{})) {
  if(!c?.startTimeText || !c?.endTimeText) continue;
  const cls=String(c.className||''); classes[cls]=(classes[cls]||0)+1;
  if(c.platformInfo?.venueName) courts.add(String(c.platformInfo.venueName));
  if(cells.length<4) cells.push({start:c.startTimeText,end:c.endTimeText,className:cls,expired:c.expired});
}
const err=layout?.$data?.error;
const visibleVerifications=[];
for(const vm of seen) {
  const o=vm.$options||{}, name=o.name||o._componentTag||'';
  if(!/NeVerify|Slider/.test(name) || !vm.$el || !vm.$el.getBoundingClientRect) continue;
  const r=vm.$el.getBoundingClientRect(), style=getComputedStyle(vm.$el);
  if(r.width>0 && r.height>0 && style.display!=='none' && style.visibility!=='hidden')
    visibleVerifications.push(name);
}
return {url:location.href,title:document.title,components,visibleVerifications,appText:root?.innerText||'',
  error:typeof err==='string'?err:(err?.message||''),
  challenge:/Access Verification|slide to verify|验证码|人机验证|安全验证/i.test(text),
  loginRequired:/请先登录|登录后查看|sign in to continue/i.test(text),
  readyState:document.readyState,language:navigator.language,webdriver:navigator.webdriver,
  browser:navigator.userAgent,tableFound:Boolean(table),classes,courts:[...courts],cells,
  resources:performance.getEntriesByType('resource').map(r=>r.name)};
"""


def redact(value: object) -> str:
    text = str(value or "")[:6000]
    text = re.sub(r"https?://[^\s\"'<>]+", "[url]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(
        r"(?i)(token|password|cookie|authorization|secret|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=[omitted]",
        text,
    )
    text = re.sub(r"[A-Za-z0-9_+/=-]{24,}", "[opaque]", text)
    return re.sub(r"\b\d{11,}\b", "[number]", text)[:3500]


def source_matches(url: str, source: str) -> bool:
    host, venue, product = SOURCES[source]
    p = urlsplit(url)
    return (
        p.scheme == "https"
        and p.netloc == host
        and p.path == f"/booking/schedule/{venue}"
        and parse_qs(p.query).get("salesItemId") == [product]
    )


def public_resource(url: str, host: str) -> str | None:
    p = urlsplit(url)
    if (
        p.scheme == "https"
        and p.netloc == host
        and re.fullmatch(r"/(?:js|static|assembly)/[A-Za-z0-9_./-]{1,160}", p.path)
    ):
        return p.path
    return None


def command_help() -> dict[str, Any]:
    candidates = [shutil.which("dsh"), str(Path.home() / ".local/bin/dsh")]
    binary = next(
        (p for p in candidates if p and os.path.isfile(p) and os.access(p, os.X_OK)), None
    )
    if not binary:
        report: dict[str, Any] = {"available": False}
        for prop in ("WorkingDirectory", "ExecStart"):
            try:
                found = subprocess.run(
                    ["systemctl", "show", "dsh-web.service", "--property=" + prop, "--value"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                ).stdout.strip()
                if prop == "WorkingDirectory" and re.fullmatch(r"/[A-Za-z0-9_./-]{1,180}", found):
                    report["workingDirectory"] = found
                if prop == "ExecStart":
                    paths = re.findall(r"(?:path=|argv\[\]=)(/[A-Za-z0-9_./-]+)", found)
                    report["launcherPaths"] = list(dict.fromkeys(paths))[:3]
            except Exception as error:
                report["errorClass"] = type(error).__name__
        return report
    try:
        result = subprocess.run(
            [binary, "--help"], capture_output=True, text=True, timeout=12, check=False
        )
        return {
            "available": True,
            "exitCode": result.returncode,
            "help": redact(result.stdout + result.stderr),
        }
    except Exception as error:
        return {"available": True, "errorClass": type(error).__name__}


def health() -> dict[str, Any]:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open("http://127.0.0.1:8788/healthz", timeout=5) as response:
            data = json.loads(response.read(4096))
        return {"ok": data.get("ok") is True}
    except Exception as error:
        return {"ok": False, "errorClass": type(error).__name__}


def classify(
    page: dict[str, Any], matched: bool, queries: list[dict[str, Any]], source: str
) -> str:
    if (
        page.get("challenge")
        or page.get("loginRequired")
        or page.get("visibleVerifications")
        or any(q.get("accessChallenge") for q in queries)
    ):
        return "human_verification_required"
    if not matched:
        return "unexpected_source"
    paths = {q.get("path", "").rsplit("/", 1)[-1] for q in queries if q.get("json") is True}
    cells = sum(page.get("classes", {}).values())
    if (
        page.get("tableFound")
        and cells > 0
        and (source == "dashah_control" or {"getVenueCalendarList", "getVenueOrderList"} <= paths)
    ):
        return "query_samples_observed_not_bookability_acceptance"
    return "schedule_component_only" if page.get("tableFound") else "initialization_incomplete"


def observe(source: str) -> dict[str, Any]:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    host, venue, product = SOURCES[source]
    report: dict[str, Any] = {"source": source, "bookabilityVerified": False}
    proc = driver = None
    binary = "/usr/lib/chromium/chromium"
    if not Path(binary).is_file():
        binary = shutil.which("chromium") or ""
    with tempfile.TemporaryDirectory(prefix="ydmap-compare-") as profile:
        try:
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            if port == 9224:
                raise RuntimeError("production_port_reserved")
            env = os.environ.copy()
            env.setdefault("DISPLAY", ":0")
            env.setdefault("XAUTHORITY", str(Path.home() / ".Xauthority"))
            env.update(LANG="zh_CN.UTF-8", LANGUAGE="zh_CN:zh", LC_ALL="zh_CN.UTF-8")
            args = [
                binary,
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
                "about:blank",
            ]
            proc = subprocess.Popen(
                args,
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
                    if proc.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError("browser_start_failed") from None
                    time.sleep(0.3)
            time.sleep(4)
            options = Options()
            options.debugger_address = f"127.0.0.1:{port}"
            options.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
            driver = webdriver.Chrome(
                service=Service(shutil.which("chromedriver") or "/usr/local/bin/chromedriver"),
                options=options,
            )
            driver.set_script_timeout(5)
            driver.set_page_load_timeout(35)
            driver.get(f"https://{host}/booking/schedule/{venue}?salesItemId={product}")
            pending: dict[str, str] = {}
            report["queries"], report["networkResources"] = [], []
            deadline = time.monotonic() + 35
            while True:
                result = driver.execute_script(PUBLIC_JS)
                if not isinstance(result, dict):
                    raise RuntimeError("invalid_browser_result")
                if (
                    result.get("challenge")
                    or result.get("loginRequired")
                    or result.get("visibleVerifications")
                ):
                    report["state"] = "human_verification_required"
                    break
                read_queries(driver, pending, report["queries"], report["networkResources"])
                state = classify(
                    result, source_matches(result.get("url", ""), source), report["queries"], source
                )
                if (
                    state
                    in (
                        "human_verification_required",
                        "unexpected_source",
                        "query_samples_observed_not_bookability_acceptance",
                    )
                    or time.monotonic() >= deadline
                ):
                    report["state"] = state
                    break
                time.sleep(1)
            report["sourceMatches"] = source_matches(result.pop("url", ""), source)
            resources = result.pop("resources", [])
            result["resources"] = list(
                dict.fromkeys(p for r in resources if (p := public_resource(r, host)))
            )[:45]
            for key in ("title", "appText", "error", "browser"):
                result[key] = redact(result.get(key))
            result["courts"] = [redact(v)[:80] for v in result.get("courts", [])[:20]]
            report["page"] = result
        except Exception as error:
            report.update(state="probe_failed", errorClass=type(error).__name__)
        finally:
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
        "observedAt": datetime.now(UTC).isoformat(),
        "mode": "same_native_launcher_different_source",
        "productionChanged": False,
        "externalTestSends": 0,
        "healthBefore": health(),
        "dshCli": command_help(),
        "sources": [],
    }
    for source in SOURCES:
        result = observe(source)
        report["sources"].append(result)
        if result["state"] == "human_verification_required":
            report["stoppedOnVerification"] = True
            break
    report["healthAfter"] = health()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
