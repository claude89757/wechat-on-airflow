#!/usr/bin/env python3
"""One ordinary-browser, isolated-profile visit per source; no availability writes."""

from __future__ import annotations

import hashlib
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

from bawtt_live_query import shape

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
const parent=table?.$parent;
let selectedDate=null;
const rawDate=parent?.curDate;
if(typeof rawDate==='number' && Number.isFinite(rawDate) && rawDate>1000000000000 && rawDate<10000000000000) {
  const date=new Date(rawDate+8*3600000); selectedDate=date.toISOString().slice(0,10);
} else if(typeof rawDate==='string' && /^\d{4}-\d{2}-\d{2}$/.test(rawDate)) selectedDate=rawDate;
const err=layout?.$data?.error;
const visibleVerifications=[];
function visibleAccessCheck(el) {
  if(!el || !el.getBoundingClientRect) return false;
  const r=el.getBoundingClientRect();
  if(r.width<=0 || r.height<=0 || r.bottom<=0 || r.right<=0 || r.top>=innerHeight || r.left>=innerWidth) return false;
  for(let ancestor=el;ancestor;ancestor=ancestor.parentElement) {
    const style=getComputedStyle(ancestor);
    if(style.display==='none' || style.visibility==='hidden' || style.visibility==='collapse' ||
       Number(style.opacity)===0 || style.contentVisibility==='hidden') return false;
  }
  return true;
}
for(const vm of seen) {
  const o=vm.$options||{}, name=o.name||o._componentTag||'';
  // Slider is the product/date strip, not a verification control (visual run35071385101).
  if(name!=='NeVerify') continue;
  if(visibleAccessCheck(vm.$el))
    visibleVerifications.push(name);
}
return {url:location.href,title:document.title,components,visibleVerifications,appText:root?.innerText||'',
  error:typeof err==='string'?err:(err?.message||''),
  challenge:/Access Verification|slide to verify|验证码|人机验证|安全验证/i.test(text),
  loginRequired:/请先登录|登录后查看|sign in to continue/i.test(text),
  readyState:document.readyState,language:navigator.language,webdriver:navigator.webdriver,
  browser:navigator.userAgent,tableFound:Boolean(table),selectedDate,selectedProduct:parent?.salesItemId,classes,courts:[...courts],cells,
  businessMethodNames: Object.keys(parent?.$options?.methods||{}).filter(k=>/^[A-Za-z_][A-Za-z0-9_]{0,60}$/.test(k)),
  businessQueryMethods: Object.entries(parent?.$options?.methods||{}).filter(([k,v])=>/calendar|venue|schedule|order/i.test(k) && /get|query|load|fetch/i.test(k) && !/sign|auth|secret|captcha|verify|fingerprint/i.test(k) && typeof v==='function').slice(0,8).map(([name,fn])=>({name,text:fn.toString().slice(0,1800)})),
  businessFieldNames: Object.keys(parent?.$data||{}).filter(k=>/^[A-Za-z_][A-Za-z0-9_]{0,60}$/.test(k)),
  businessFlags: Object.fromEntries(Object.entries(parent?.$data||{}).filter(([k,v])=>/^(loading|isLoading|tableLoading|ready|isReady|initializing|error|errorCode|saleStatus|status|success|curDate|salesItemId)$/.test(k) && (v===null || ['boolean','number'].includes(typeof v)))),
  bookingContext: Object.fromEntries(Object.entries(table?.$parent?.$data||{}).filter(([k])=>/^(curDate|date|currentDate|selectedDate|bookingDate|salesItemId|salesItemList|calendarList|venueCalendarList|platformList|venueList|orderList)$/.test(k))),
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
        and {"getVenueCalendarList", "getVenueOrderList"} <= paths
    ):
        return "query_samples_observed_not_bookability_acceptance"
    if page.get("tableFound") and cells > 0:
        return "schedule_cells_observed_without_query_samples"
    return "schedule_component_only" if page.get("tableFound") else "initialization_incomplete"


def loaded_business_evidence(driver: Any, source: str) -> list[dict[str, Any]]:
    """Read already-loaded public business resources, never fetch or replay a request."""
    host = SOURCES[source][0]
    tree = driver.execute_cdp_cmd("Page.getResourceTree", {})["frameTree"]
    frame_id = tree["frame"]["id"]
    urls = driver.execute_script("return performance.getEntriesByType('resource').map(r=>r.name)")
    metadata = {item["url"]: item for item in tree.get("resources", [])}
    reports: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r"/srv[0-9]+/api/pub/sport/venue/"
        r"(?:getSalesItemList|getSportVenueConfig|getVenueCalendarList|getVenueOrderList)$"
    )
    for url in urls:
        parsed = urlsplit(url)
        is_script = parsed.path == "/js/booking-schedule-venue.b6226c5c.js"
        if (
            parsed.scheme != "https"
            or parsed.netloc != host
            or not (is_script or pattern.fullmatch(parsed.path))
            or parsed.path in seen
        ):
            continue
        seen.add(parsed.path)
        item: dict[str, Any] = {
            "path": parsed.path,
            "kind": "public_business_script" if is_script else "public_booking_query",
            "httpStatusObserved": False,
            "mimeType": metadata.get(url, {}).get("mimeType"),
        }
        try:
            response = driver.execute_cdp_cmd(
                "Page.getResourceContent", {"frameId": frame_id, "url": url}
            )
            content = response.get("content", "")
            if (
                not isinstance(content, str)
                or len(content) > 1000000
                or response.get("base64Encoded")
            ):
                item["reason"] = "nontext_or_oversized_resource"
            else:
                item["bytes"] = len(content.encode())
                item["sha256"] = hashlib.sha256(content.encode()).hexdigest()
                item["accessChallenge"] = bool(
                    re.search(
                        r"Access Verification|slide to verify|aliyun_waf|验证码|人机验证",
                        content[:2000],
                        re.I,
                    )
                )
                if item["accessChallenge"]:
                    item["reason"] = "verification_response_stop"
                elif is_script:
                    excerpts = []
                    for term in (
                        "getVenueCalendarList",
                        "getVenueOrderList",
                        "getSportVenueConfig",
                        "getSalesItemList",
                        "className:",
                        "col-completed",
                        "not-open",
                        "created:",
                        "mounted:",
                    ):
                        matches = list(re.finditer(re.escape(term), content))
                        for match in matches[:2]:
                            excerpts.append(
                                {
                                    "term": term,
                                    "matches": len(matches),
                                    "text": redact(
                                        content[max(0, match.start() - 200) : match.end() + 800]
                                    ),
                                }
                            )
                    item["businessExcerpts"] = excerpts
                else:
                    try:
                        value = json.loads(content)
                        item["jsonParsed"] = True
                        item["schema"] = shape(value)
                        item["businessSuccessVerified"] = False
                    except ValueError:
                        item["jsonParsed"] = False
        except Exception as error:
            item["readErrorClass"] = type(error).__name__
        reports.append(item)
        if item.get("accessChallenge"):
            break
    return reports


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
                f"https://{host}/booking/schedule/{venue}?salesItemId={product}",
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
            driver = webdriver.Chrome(
                service=Service(shutil.which("chromedriver") or "/usr/local/bin/chromedriver"),
                options=options,
            )
            driver.set_script_timeout(5)
            data_wait_started = time.monotonic()
            deadline = data_wait_started + 35
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
                state = classify(result, source_matches(result.get("url", ""), source), [], source)
                if (
                    state
                    in (
                        "human_verification_required",
                        "unexpected_source",
                        "query_samples_observed_not_bookability_acceptance",
                        "schedule_cells_observed_without_query_samples",
                    )
                    or time.monotonic() >= deadline
                ):
                    report["state"] = state
                    break
                time.sleep(1)
            report["dataWaitSeconds"] = round(time.monotonic() - data_wait_started, 2)
            report["sourceMatches"] = source_matches(result.pop("url", ""), source)
            resources = result.pop("resources", [])
            result["resources"] = list(
                dict.fromkeys(p for r in resources if (p := public_resource(r, host)))
            )[:45]
            for key in ("title", "appText", "error", "browser"):
                result[key] = redact(result.get(key))
            result["courts"] = [redact(v)[:80] for v in result.get("courts", [])[:20]]
            result["bookingContext"] = shape(result.get("bookingContext", {}))
            for method in result.get("businessQueryMethods", []):
                method["text"] = redact(method["text"])
            report["page"] = result
            if report["sourceMatches"] and report.get("state") != "human_verification_required":
                try:
                    report["loadedBusinessEvidence"] = loaded_business_evidence(driver, source)
                    if any(item.get("accessChallenge") for item in report["loadedBusinessEvidence"]):
                        report["state"] = "human_verification_required"
                except Exception as error:
                    report["businessEvidenceErrorClass"] = type(error).__name__
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
