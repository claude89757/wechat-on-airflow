#!/usr/bin/env python3
"""Bounded ordinary-browser diagnosis; no site verification or service mutation."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

TARGETS = {"indoor": "111317", "outdoor": "103224"}


def public_text(value: object) -> str:
    text = str(value or "")[:1600]
    text = re.sub(r"https?://[^\s\"<>]+", "[URL]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[email]", text)
    text = re.sub(
        r"(?i)(token|cookie|secret|password|authorization|traceid)\s*[:=]\s*\S+",
        r"\1=[omitted]",
        text,
    )
    text = re.sub(r"[A-Za-z0-9_+/.=-]{24,}", "[opaque]", text)
    text = re.sub(r"\b\d{5,}\b", "[number]", text)
    return text[:900]


def diagnose() -> dict[str, Any]:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    report: dict[str, Any] = {
        "mode": "public_ui_failure_diagnosis",
        "observedAt": datetime.now(UTC).isoformat(),
        "productionChanged": False,
        "externalTestSends": 0,
        "targets": [],
    }
    driver = None
    os.environ.setdefault("DISPLAY", ":0")
    with tempfile.TemporaryDirectory(prefix="bawtt-ui-diagnosis-") as profile:
        try:
            options = Options()
            options.binary_location = shutil.which("chromium") or "/usr/lib/chromium/chromium"
            options.add_argument(f"--user-data-dir={profile}")
            options.add_argument("--no-first-run")
            options.add_argument("--window-size=1280,900")
            options.set_capability("goog:loggingPrefs", {"browser": "ALL", "performance": "ALL"})
            binary = shutil.which("chromedriver") or "/usr/local/bin/chromedriver"
            driver = webdriver.Chrome(service=Service(binary), options=options)
            driver.set_page_load_timeout(35)
            driver.set_script_timeout(5)
            for target, product in TARGETS.items():
                driver.get_log("performance")
                driver.get_log("browser")
                driver.get(f"https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId={product}")
                challenge = False
                for _ in range(15):
                    text = driver.execute_script(
                        "return document.body ? document.body.innerText : ''"
                    )
                    challenge = bool(
                        re.search(
                            r"Access Verification|slide to verify|验证码|人机验证|安全验证",
                            text,
                            re.I,
                        )
                    )
                    if challenge:
                        break
                    time.sleep(1)
                page = driver.execute_script("""
                const root = document.querySelector('#app');
                return {title:document.title, text:document.body.innerText,
                  appText:root ? root.innerText : '',
                  vue2:Boolean(root && root.__vue__), vue3:Boolean(root && root.__vue_app__),
                  appChildren:root ? [...root.children].map(e=>e.tagName+':'+e.className).slice(0,10) : [],
                  iframeCount:document.querySelectorAll('iframe').length,
                  scriptCount:document.scripts.length,
                  readyState:document.readyState};
                """)
                item: dict[str, Any] = {
                    "target": target,
                    "salesItemId": product,
                    "challenge": challenge,
                    "page": {
                        k: public_text(v) if isinstance(v, str) else v
                        for k, v in page.items()
                        if k != "appChildren"
                    },
                    "appChildren": [public_text(v) for v in page["appChildren"]],
                    "console": [],
                    "resources": [],
                }
                for entry in driver.get_log("browser")[:20]:
                    item["console"].append(
                        {"level": entry.get("level"), "message": public_text(entry.get("message"))}
                    )
                for entry in driver.get_log("performance"):
                    event = json.loads(entry["message"])["message"]
                    if event.get("method") != "Network.responseReceived":
                        continue
                    response = event["params"]["response"]
                    parsed = urlsplit(response.get("url", ""))
                    if parsed.hostname != "bawtt.ydmap.cn" or not re.fullmatch(
                        r"/[A-Za-z0-9_./-]{1,180}", parsed.path
                    ):
                        continue
                    if len(item["resources"]) < 50:
                        item["resources"].append(
                            {
                                "path": parsed.path,
                                "status": response.get("status"),
                                "mime": response.get("mimeType"),
                            }
                        )
                report["targets"].append(item)
                if challenge:
                    report["reason"] = "stopped_on_verification"
                    break
        except Exception as error:
            report["errorClass"] = type(error).__name__
        finally:
            if driver is not None:
                driver.quit()
    return report


if __name__ == "__main__":
    print(json.dumps(diagnose(), ensure_ascii=False, sort_keys=True))
