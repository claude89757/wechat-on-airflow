#!/usr/bin/env python3
"""Read-only control-page screenshot and non-secret DSH executable discovery."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

from ydmap_source_compare import PUBLIC_JS, redact, source_matches

DETAIL_JS = r"""
const root=document.querySelector('#app')?.__vue__, seen=new Set(), found=[];
function walk(vm) {
  if(!vm || seen.has(vm) || seen.size>100) return;
  seen.add(vm); const name=vm.$options?.name||vm.$options?._componentTag||'';
  if(/NeVerify|Slider/.test(name) && vm.$el?.getBoundingClientRect) {
    const chain=[]; let el=vm.$el;
    for(let i=0;el && i<12;i++,el=el.parentElement) {
      const s=getComputedStyle(el),r=el.getBoundingClientRect();
      chain.push({tag:el.tagName,display:s.display,visibility:s.visibility,
        opacity:s.opacity,left:r.left,top:r.top,width:r.width,height:r.height,
        overflow:s.overflow,position:s.position});
    }
    found.push({name,text:(vm.$el.innerText||'').slice(0,120),chain});
  }
  for(const child of vm.$children||[]) walk(child);
}
walk(root); return {viewport:{width:innerWidth,height:innerHeight},candidates:found};
"""


def dsh_entrypoints() -> list[str]:
    raw = subprocess.run(
        ["systemctl", "show", "dsh-web.service", "--property=ExecStart", "--value"],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    ).stdout
    match = re.search(r"argv\[\]=(.*?)(?: ; | ;}|$)", raw)
    args = shlex.split(match.group(1)) if match else []
    return [
        p
        for p in args[1:]
        if re.fullmatch(r"/[A-Za-z0-9_@+./-]{1,220}", p)
        and re.search(r"dsh|deepseek", p, re.I)
        and (
            Path(p).suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
            or Path(p).name == "dsh"
        )
    ][:5]


def main() -> None:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    report: dict[str, Any] = {
        "productionChanged": False,
        "externalTestSends": 0,
        "bookabilityVerified": False,
        "dshProgramPaths": dsh_entrypoints(),
    }
    proc = driver = None
    with tempfile.TemporaryDirectory(prefix="ydmap-visual-control-") as profile:
        try:
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                port = reserve.getsockname()[1]
            if port == 9224:
                raise RuntimeError("reserved_port")
            env = os.environ.copy()
            env.setdefault("DISPLAY", ":0")
            env.setdefault("XAUTHORITY", str(Path.home() / ".Xauthority"))
            env.update(LANG="zh_CN.UTF-8", LANGUAGE="zh_CN:zh", LC_ALL="zh_CN.UTF-8")
            args = [
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
                "https://wxsports.ydmap.cn/booking/schedule/100220?salesItemId=100000",
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
                    if time.monotonic() >= deadline or proc.poll() is not None:
                        raise RuntimeError("browser_start_failed") from None
                    time.sleep(0.2)
            time.sleep(4)
            options = Options()
            options.debugger_address = f"127.0.0.1:{port}"
            driver = webdriver.Chrome(
                service=Service(shutil.which("chromedriver") or "/usr/local/bin/chromedriver"),
                options=options,
            )
            driver.set_script_timeout(5)
            page = driver.execute_script(PUBLIC_JS)
            if not source_matches(page.pop("url", ""), "dashah_control"):
                raise RuntimeError("unexpected_source")
            detail = driver.execute_script(DETAIL_JS)
            for item in detail["candidates"]:
                item["text"] = redact(item["text"])
            report["controlPage"] = {
                k: page[k]
                for k in ("tableFound", "challenge", "loginRequired", "classes", "courts")
            }
            report["visibleCandidates"] = detail
            image = driver.get_screenshot_as_base64()
            if len(image) > 1400000:
                raise RuntimeError("oversized_screenshot")
            report["screenshotPNGBase64"] = image
            report["state"] = "visual_evidence_captured_no_interaction"
        except Exception as error:
            report.update(state="visual_diagnosis_failed", errorClass=type(error).__name__)
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
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
