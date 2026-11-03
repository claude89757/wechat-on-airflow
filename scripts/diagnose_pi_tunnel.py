#!/usr/bin/env python3
"""One-shot protected Pi tunnel diagnosis; never print credentials or raw logs."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re

MAX_REPORT_BYTES = 65536
CATEGORIES = (
    "connected",
    "connection_lost",
    "timeout",
    "dns_failure",
    "network_unreachable",
    "connection_refused",
    "authentication",
    "permission",
    "oom",
    "shutdown",
    "other_error",
)
STATES = {
    "active",
    "inactive",
    "failed",
    "activating",
    "deactivating",
    "reloading",
    "running",
    "dead",
    "exited",
    "start",
    "stop",
    "auto-restart",
    "listening",
    "loaded",
    "not-found",
    "masked",
    "error",
    "success",
    "exit-code",
    "signal",
    "core-dump",
    "timeout",
    "resources",
    "start-limit-hit",
    "oom-kill",
    "unknown",
    "created",
    "restarting",
    "paused",
    "removing",
}
REMOTE_PROBE = r"""
import json
import os
import re
import subprocess
import selectors
import time
from pathlib import Path

DEADLINE = time.monotonic() + 240

PATTERNS = {
    "connected": (("registered tunnel connection",), ("connection registered",)),
    "connection_lost": (("connection closed",), ("connection terminated",), ("lost connection",), ("failed to serve",)),
    "timeout": (("timeout",), ("timed out",), ("deadline exceeded",)),
    "dns_failure": (("no such host",), ("dns", "fail"), ("lookup", "fail"), ("name resolution",)),
    "network_unreachable": (("network is unreachable",), ("no route to host",)),
    "connection_refused": (("connection refused",),),
    "authentication": (("unauthorized",), ("authentication", "fail"), ("invalid", "token"), ("invalid", "credential")),
    "permission": (("permission denied",), ("access denied",)),
    "oom": (("out of memory",), ("oom", "kill"), ("killed process",)),
    "shutdown": (("graceful shutdown",), ("stopping tunnel",), ("received", "signal")),
    "other_error": (("error",), ("fatal",), ("panic",)),
}

def command(argv):
    process = None
    selector = selectors.DefaultSelector()
    try:
        if time.monotonic() >= DEADLINE:
            return -1, ""
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        selector.register(process.stdout, selectors.EVENT_READ)
        chunks = []
        total = 0
        deadline = min(DEADLINE, time.monotonic() + 15)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            for key, _ in selector.select(min(remaining, 0.5)):
                chunk = os.read(key.fileobj.fileno(), min(65536, 2000001 - total))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > 2000000:
                    raise ValueError("output limit")
                chunks.append(chunk)
        code = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return code, b"".join(chunks).decode(errors="replace")
    except Exception:
        return -1, ""
    finally:
        selector.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout is not None:
                process.stdout.close()

def categories(raw):
    counts = {key: 0 for key in PATTERNS}
    for line in raw.splitlines():
        line = line.lower()
        for key, groups in PATTERNS.items():
            if any(all(term in line for term in group) for group in groups):
                counts[key] += 1
    return counts

def collect():
    report = {"readOnly": True, "systemd": [], "docker": []}
    try:
        report["uptimeSeconds"] = int(float(Path("/proc/uptime").read_text().split()[0]))
        stat = os.statvfs("/")
        report["rootFreeBytes"] = stat.f_bavail * stat.f_frsize
    except Exception:
        pass
    rc, units = command(["systemctl", "list-units", "--all", "--type=service", "--no-legend", "--plain", "cloudflared*"])
    report["systemdQueryOk"] = rc == 0
    names = [line.split()[0] for line in units.splitlines() if line.split()]
    names = [name for name in names if re.fullmatch(r"cloudflared[A-Za-z0-9_.@-]*\.service", name)]
    if "cloudflared.service" not in names:
        names.insert(0, "cloudflared.service")
    props = ["LoadState", "ActiveState", "SubState", "Result", "ExecMainCode", "ExecMainStatus", "NRestarts"]
    for name in names[:8]:
        rc, output = command(["systemctl", "show", name, "--property=" + ",".join(props)])
        row = {"queryOk": rc == 0}
        for line in output.splitlines():
            key, sep, value = line.partition("=")
            if sep and key in props:
                row[key] = value
        rc, logs = command(["journalctl", "--no-pager", "-q", "-u", name, "--since=-6h", "-n", "1000", "-o", "cat"])
        row["journalQueryOk"] = rc == 0
        row["journalLineCount"] = len(logs.splitlines())
        row["logCategories"] = categories(logs)
        report["systemd"].append(row)
    rc, rows = command(["docker", "ps", "-a", "--format", "{{.ID}}\t{{.Image}}\t{{.Names}}"])
    report["dockerQueryOk"] = rc == 0
    for line in rows.splitlines():
        parts = line.split("\t")
        if len(parts) != 3 or not re.fullmatch(r"[0-9a-f]{12,64}", parts[0]):
            continue
        if "cloudflared" not in (parts[1] + " " + parts[2]).lower():
            continue
        if len(report["docker"]) >= 8:
            break
        cid = parts[0]
        template = '{{json .State.Status}}|{{.State.Running}}|{{.State.OOMKilled}}|{{.State.ExitCode}}|{{.RestartCount}}'
        rc, state = command(["docker", "inspect", "--format", template, cid])
        fields = state.strip().split("|")
        row = {"queryOk": rc == 0}
        if len(fields) == 5:
            row.update({"status": fields[0].strip('"'), "running": fields[1] == "true",
                        "oomKilled": fields[2] == "true", "exitCode": fields[3], "restartCount": fields[4]})
        rc, raw = command(["docker", "logs", "--since=6h", "--tail=1000", cid])
        row["journalQueryOk"] = rc == 0
        row["journalLineCount"] = len(raw.splitlines()) if rc == 0 else 0
        row["logCategories"] = categories(raw) if rc == 0 else {}
        report["docker"].append(row)
    print(json.dumps(report, separators=(",", ":")))

collect()
"""


def bounded_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 10**18:
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,18}", value):
        return int(value)
    return None


def safe_report(value: object) -> dict[str, object]:
    """Allowlist output even if a remote response includes unexpected private text."""
    if not isinstance(value, dict) or value.get("readOnly") is not True:
        raise ValueError("invalid report")
    report: dict[str, object] = {"readOnly": True}
    for key in ("uptimeSeconds", "rootFreeBytes"):
        report[key] = bounded_int(value.get(key))
    for key in ("systemdQueryOk", "dockerQueryOk"):
        report[key] = value.get(key) is True
    for section in ("systemd", "docker"):
        rows = value.get(section, [])
        if not isinstance(rows, list):
            raise ValueError("invalid section")
        safe_rows = []
        for row in rows[:8]:
            if not isinstance(row, dict):
                continue
            clean: dict[str, object] = {}
            for key in ("queryOk", "journalQueryOk", "running", "oomKilled"):
                if key in row:
                    clean[key] = row[key] is True
            for key in ("LoadState", "ActiveState", "SubState", "Result", "status"):
                if key in row:
                    clean[key] = row[key] if row[key] in STATES else "unknown"
            for key in (
                "ExecMainCode",
                "ExecMainStatus",
                "NRestarts",
                "exitCode",
                "restartCount",
                "journalLineCount",
            ):
                if key in row:
                    clean[key] = bounded_int(row[key])
            counts = row.get("logCategories", {})
            clean["logCategories"] = (
                {key: bounded_int(counts.get(key)) for key in CATEGORIES}
                if isinstance(counts, dict)
                else {}
            )
            safe_rows.append(clean)
        report[section] = safe_rows
    return report


def main() -> int:
    import paramiko

    class PinnedHostKey(paramiko.MissingHostKeyPolicy):
        def missing_host_key(self, client, hostname, key):
            actual = "SHA256:" + base64.b64encode(
                hashlib.sha256(key.asbytes()).digest()
            ).decode().rstrip("=")
            if not hmac.compare_digest(actual, fingerprint):
                raise paramiko.SSHException("host_key_mismatch")

    required = (
        "PI_DEVICE_SSH_HOST",
        "PI_DEVICE_SSH_PORT",
        "PI_DEVICE_SSH_USER",
        "PI_DEVICE_SSH_PASSWORD",
        "PI_DEVICE_SSH_HOST_KEY_SHA256",
    )
    report: dict[str, object] = {
        "readOnly": True,
        "sshAuthenticated": False,
        "configurationChanged": False,
    }
    client = paramiko.SSHClient()
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    try:
        if any(not os.environ.get(key) for key in required):
            raise ValueError("protected configuration missing")
        fingerprint = os.environ[required[4]].strip().rstrip("=")
        if not re.fullmatch(r"SHA256:[A-Za-z0-9+/]{43}", fingerprint):
            raise ValueError("invalid fingerprint")
        port = int(os.environ[required[1]])
        if not 1 <= port <= 65535:
            raise ValueError("invalid port")
        client.set_missing_host_key_policy(PinnedHostKey())
        client.connect(
            hostname=os.environ[required[0]],
            port=port,
            username=os.environ[required[2]],
            password=os.environ[required[3]],
            look_for_keys=False,
            allow_agent=False,
            timeout=15,
            auth_timeout=15,
            banner_timeout=15,
            disabled_algorithms={"keys": ["ssh-rsa"], "pubkeys": ["ssh-rsa"]},
        )
        report["sshAuthenticated"] = True
        stdin, stdout, stderr = client.exec_command("python3 -", timeout=300)
        stdin.write(REMOTE_PROBE)
        stdin.flush()
        stdin.channel.shutdown_write()
        raw = stdout.read(MAX_REPORT_BYTES + 1)
        if len(raw) > MAX_REPORT_BYTES:
            raise ValueError("oversized report")
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError("remote probe failed")
        report["host"] = safe_report(json.loads(raw))
        report["ok"] = True
    except Exception as exc:
        report["ok"] = False
        # Never print exception text: it can contain hostnames, credentials, or raw output.
        report["errorClass"] = type(exc).__name__
    finally:
        client.close()
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
