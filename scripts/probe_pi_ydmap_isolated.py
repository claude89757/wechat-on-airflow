#!/usr/bin/env python3
"""One-off Raspberry Pi YDMap probe that must not touch the Dashah scraper."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shlex
from typing import Any

import paramiko

BOOKING_URL = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317"
ISOLATED_DEBUG_PORT = 9335
ISOLATED_PROFILE = "/tmp/bawtt_ydmap_probe_profile"
DSH_DEBUG_PORT = 9224
DSH_HEALTH_URL = "http://127.0.0.1:8788/healthz"
DSH_SERVICE = "dsh-ydmap-scraper"
REQUIRED_ENV = (
    "PI_DEVICE_SSH_HOST",
    "PI_DEVICE_SSH_PORT",
    "PI_DEVICE_SSH_USER",
    "PI_DEVICE_SSH_PASSWORD",
    "PI_DEVICE_SSH_HOST_KEY_SHA256",
)

REMOTE_PROBE = r"""
import json
import os
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

BOOKING_URL = "https://bawtt.ydmap.cn/booking/schedule/104036?salesItemId=111317"
ISOLATED_DEBUG_PORT = 9335
ISOLATED_PROFILE = "/tmp/bawtt_ydmap_probe_profile"
DSH_DEBUG_PORT = 9224
DSH_HEALTH_URL = "http://127.0.0.1:8788/healthz"
DSH_SERVICE = "dsh-ydmap-scraper"
CHROMIUM_BIN = "/usr/lib/chromium/chromium"
CHROMEDRIVER = "/usr/local/bin/chromedriver"
UA = (
    "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/137.0.7151.119 Safari/537.36"
)
EXTRACT_DAY_JS = r'''
const bodyText = document.body && document.body.innerText || '';
const captcha = /Access Verification|slide to verify|访问验证|拖动滑块|完成拼图/.test(bodyText);
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
  courts,
  courtNames,
  cellCount,
  bodyPreview: bodyText.slice(0, 180),
};
'''


def port_open(port):
    sock = socket.socket()
    sock.settimeout(0.3)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()


def dsh_status():
    service = subprocess.run(
        ["systemctl", "is-active", DSH_SERVICE],
        check=False,
        capture_output=True,
        text=True,
    ).stdout.strip()
    healthy = False
    try:
        with urllib.request.urlopen(DSH_HEALTH_URL, timeout=3) as resp:
            payload = json.loads(resp.read().decode())
            healthy = payload.get("ok") is True and payload.get("service") == "dsh_ydmap"
    except Exception:
        healthy = False
    return {
        "service": service,
        "healthz": healthy,
        "scrape_port_busy": port_open(DSH_DEBUG_PORT),
        "loopback_open": port_open(8788),
    }


def wait_dsh_idle():
    deadline = time.time() + 90
    last = dsh_status()
    while time.time() < deadline:
        last = dsh_status()
        if last["healthz"] and not last["scrape_port_busy"]:
            return last
        time.sleep(3)
    return last


def kill_isolated():
    subprocess.run(
        ["pkill", "-f", f"remote-debugging-port={ISOLATED_DEBUG_PORT}"],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def emit(result, code):
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


def main():
    before = wait_dsh_idle()
    result = {
        "ok": False,
        "captcha": False,
        "ready": False,
        "court_names": [],
        "available_court_count": 0,
        "slot_count": 0,
        "cell_count": 0,
        "error": None,
        "dsh_before": before,
        "dsh_after": before,
        "isolated": {
            "debug_port": ISOLATED_DEBUG_PORT,
            "profile": ISOLATED_PROFILE,
            "booking_host": "bawtt.ydmap.cn",
        },
    }
    if not before["healthz"] or before["service"] != "active":
        result["error"] = "dsh_not_healthy"
        return emit(result, 2)
    if before["scrape_port_busy"]:
        result["error"] = "dsh_scrape_in_progress"
        return emit(result, 3)

    kill_isolated()
    time.sleep(1)
    profile = Path(ISOLATED_PROFILE)
    if profile.exists():
        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY") or ":0"
    env.setdefault("XAUTHORITY", "/home/claude/.Xauthority")
    env["LANG"] = "zh_CN.UTF-8"
    env["LANGUAGE"] = "zh_CN:zh"
    env["LC_ALL"] = "zh_CN.UTF-8"
    proc = subprocess.Popen(
        [
            CHROMIUM_BIN,
            f"--remote-debugging-port={ISOLATED_DEBUG_PORT}",
            "--remote-allow-origins=*",
            f"--user-data-dir={ISOLATED_PROFILE}",
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
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    driver = None
    try:
        deadline = time.time() + 40
        last = ""
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{ISOLATED_DEBUG_PORT}/json/version", timeout=1
                ) as resp:
                    json.loads(resp.read().decode())
                    break
            except Exception as exc:
                last = str(exc)
                time.sleep(0.4)
        else:
            result["error"] = "devtools_not_ready"
            return emit(result, 4)

        time.sleep(4)
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        opts = Options()
        opts.debugger_address = f"127.0.0.1:{ISOLATED_DEBUG_PORT}"
        driver = webdriver.Chrome(service=Service(CHROMEDRIVER), options=opts)
        extracted = {}
        wait_deadline = time.time() + 45
        while time.time() < wait_deadline:
            extracted = driver.execute_script(EXTRACT_DAY_JS) or {}
            if extracted.get("captcha") or extracted.get("ready"):
                break
            time.sleep(1.5)
        courts = extracted.get("courts") or {}
        names = extracted.get("courtNames") or []
        captcha = bool(extracted.get("captcha"))
        ready = bool(extracted.get("ready"))
        result.update(
            {
                "ok": ready and not captcha,
                "captcha": captcha,
                "ready": ready,
                "court_names": names,
                "available_court_count": len(courts),
                "slot_count": sum(len(slots) for slots in courts.values()),
                "cell_count": int(extracted.get("cellCount") or 0),
                "error": None if ready and not captcha else ("captcha" if captcha else "schedule_not_ready"),
                "body_preview": extracted.get("bodyPreview") or "",
            }
        )
        return emit(result, 0)
    finally:
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
        kill_isolated()
        shutil.rmtree(ISOLATED_PROFILE, ignore_errors=True)


if __name__ == "__main__":
    code = main()
    after = dsh_status()
    # The first JSON line is the probe; a second line carries the Dashah post-check.
    print(json.dumps({"dsh_after": after}, ensure_ascii=False, sort_keys=True))
    if after.get("healthz") is not True or after.get("service") != "active":
        raise SystemExit(6)
    raise SystemExit(code)
"""


class OpsError(RuntimeError):
    pass


def normalize_sha256_host_key(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("SHA256:"):
        raise OpsError("SSH host key fingerprint must use the SHA256:<base64> format")
    encoded = value.removeprefix("SHA256:").rstrip("=")
    if not encoded:
        raise OpsError("SSH host key fingerprint payload is empty")
    padded = encoded + ("=" * (-len(encoded) % 4))
    try:
        digest = base64.b64decode(padded, validate=True)
    except ValueError as exc:
        raise OpsError("SSH host key fingerprint is not valid base64") from exc
    if len(digest) != hashlib.sha256().digest_size:
        raise OpsError("SSH host key fingerprint must contain a SHA-256 digest")
    return f"SHA256:{encoded}"


def sha256_host_key_fingerprint(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    encoded = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{encoded}"


class PinnedSHA256HostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected_fingerprint: str) -> None:
        self.expected_fingerprint = normalize_sha256_host_key(expected_fingerprint)

    def missing_host_key(
        self,
        client: paramiko.SSHClient,
        hostname: str,
        key: paramiko.PKey,
    ) -> None:
        del client
        actual = sha256_host_key_fingerprint(key)
        if not hmac.compare_digest(actual, self.expected_fingerprint):
            raise paramiko.SSHException("SSH host key verification failed")


def config_from_environment() -> dict[str, str]:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name, "")]
    if missing:
        raise OpsError("missing required environment keys: " + ", ".join(missing))
    return {name: os.environ[name] for name in REQUIRED_ENV}


def exec_remote(config: dict[str, str], command: str, timeout_seconds: int = 180) -> str:
    ssh = paramiko.SSHClient()
    try:
        ssh.set_missing_host_key_policy(
            PinnedSHA256HostKeyPolicy(config["PI_DEVICE_SSH_HOST_KEY_SHA256"])
        )
        ssh.connect(
            hostname=config["PI_DEVICE_SSH_HOST"],
            port=int(config["PI_DEVICE_SSH_PORT"]),
            username=config["PI_DEVICE_SSH_USER"],
            password=config["PI_DEVICE_SSH_PASSWORD"],
            allow_agent=False,
            look_for_keys=False,
            timeout=min(timeout_seconds, 30),
            auth_timeout=30,
            banner_timeout=30,
            disabled_algorithms={"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
        )
        _, stdout, stderr = ssh.exec_command(command, timeout=timeout_seconds)
        status = stdout.channel.recv_exit_status()
        output = stdout.read().decode(errors="replace")
        error = stderr.read().decode(errors="replace")
        if status != 0 and not output.strip():
            raise OpsError(f"remote probe failed with status {status}")
        if not output.strip():
            raise OpsError(error.strip() or f"remote probe failed with status {status}")
        return output
    finally:
        ssh.close()


def probe() -> dict[str, Any]:
    config = config_from_environment()
    encoded = base64.b64encode(REMOTE_PROBE.encode()).decode()
    command = (
        "tmp=$(mktemp /tmp/bawtt_ydmap_probe_run.XXXXXX.py); "
        "trap 'rm -f \"$tmp\"' EXIT; "
        f'printf %s {shlex.quote(encoded)} | base64 -d > "$tmp"; '
        'python3 "$tmp"'
    )
    raw = exec_remote(config, command, timeout_seconds=180)
    payload: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line.strip().startswith("{"):
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            payload.update(parsed)
    if not payload:
        raise OpsError("remote probe did not return JSON")
    return payload


def main() -> None:
    payload = probe()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    after = payload.get("dsh_after")
    if not isinstance(after, dict) or after.get("healthz") is not True:
        raise SystemExit(6)
    if payload.get("error") in {"dsh_not_healthy", "dsh_scrape_in_progress", "devtools_not_ready"}:
        raise SystemExit(2)


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from exc
