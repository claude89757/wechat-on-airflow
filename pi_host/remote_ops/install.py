"""Protected additive installation of the independent administrator MCP."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

BASE = Path("/opt/zacks-ops-mcp")
CONFIG = Path("/etc/zacks-ops-mcp")
HASHES = {
    "armv7l": "c9057c6a3b8fbb9651ed115c1e96d4a7281b7b9c9ca89fa05865c98ed7ffd437",
    "x64": "1805bcd35e6815559bd2eb97db438d3fdb0eb3a5e6a977b7c1badca76337e9ce",
    "arm64": "6287aa46b6c375d816e63ae66d024fbbfd70404825aabdfdf898a970871d2f4b",
}


def run(args):
    # The host bootstrap must run before an isolated modern runtime exists.
    return subprocess.run(  # noqa: UP022
        args,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,  # noqa: UP021
        timeout=120,
    ).stdout


def unlink(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def within(path, root):
    return os.path.commonpath([str(path), str(root)]) == str(root)


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def unpack(archive, destination):
    with tarfile.open(archive) as handle:
        root = destination.resolve()
        for member in handle.getmembers():
            target = (root / member.name).resolve()
            if not within(target, root) or member.isdev() or member.isfifo():
                raise ValueError("unsafe_archive")
            if member.issym() or member.islnk():
                link = (target.parent / member.linkname).resolve()
                if not within(link, root):
                    raise ValueError("unsafe_link")
        if hasattr(tarfile, "data_filter"):
            handle.extractall(root, filter="data")
        else:
            handle.extractall(root)


def health():
    with urllib.request.urlopen("http://127.0.0.1:3340/healthz", timeout=5) as response:
        return json.load(response)


def preflight():
    bits = run(["getconf", "LONG_BIT"]).strip()
    arch = (
        "armv7l"
        if bits == "32" and platform.machine() in {"aarch64", "armv7l"}
        else {"x86_64": "x64", "aarch64": "arm64"}.get(platform.machine())
    )
    current = BASE / "current"
    with socket.socket() as probe:
        probe.settimeout(2)
        occupied = probe.connect_ex(("127.0.0.1", 3340)) == 0
    checks = {
        "architectureSupported": arch in HASHES,
        "cloudflaredAvailable": bool(shutil.which("cloudflared")),
        "systemdAvailable": bool(shutil.which("systemctl")),
        "originPortAvailableOrOwned": not occupied or current.is_symlink(),
        "diskSpaceReady": shutil.disk_usage("/opt").free >= 600_000_000,
    }
    return {
        "ok": all(checks.values()),
        "architecture": arch,
        "installed": current.is_symlink(),
        "checks": checks,
    }


def activate(args, value):
    state = preflight()
    if not state["ok"]:
        raise RuntimeError("host_prerequisite_missing")
    arch = state["architecture"]
    node_archive = args.staging / f"node-{arch}.tar.xz"
    source = args.staging / "source.tar.gz"
    if hashlib.sha256(node_archive.read_bytes()).hexdigest() != HASHES[arch]:
        raise ValueError("node_hash_mismatch")
    if hashlib.sha256(source.read_bytes()).hexdigest() != args.source_sha256:
        raise ValueError("source_hash_mismatch")
    BASE.mkdir(parents=True, exist_ok=True, mode=0o700)
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    node = BASE / f"node-v22.23.4-linux-{arch}"
    if not node.exists():
        unpack(node_archive, BASE)
    candidate = BASE / "releases" / args.commit
    candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
    unpack(source, candidate)
    run([str(node / "bin/node"), "--check", str(candidate / "server.mjs")])
    old_current = (BASE / "current").resolve() if (BASE / "current").is_symlink() else None
    old_config = (
        json.loads((CONFIG / "runtime.json").read_text())
        if (CONFIG / "runtime.json").exists()
        else None
    )
    private_json(
        CONFIG / "rollback.json",
        {"current": str(old_current) if old_current else None, "runtime": old_config},
    )
    private_json(CONFIG / "runtime.json", {**value["runtime"], "commit": args.commit, "port": 3340})
    private_json(CONFIG / "cloudflare.json", value["credentials"])
    private_json(CONFIG / "tunnel.json", {})
    token_file = CONFIG / "tunnel_token"
    fd = os.open(token_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value["credentials"]["tunnel_token"])
    logs = Path("/var/log/zacks-ops-mcp")
    logs.mkdir(mode=0o700, exist_ok=True)
    temp = BASE / "next"
    unlink(temp)
    temp.symlink_to(candidate)
    os.replace(temp, BASE / "current")
    unit = f"""[Unit]
Description=Zacks human-confirmed administrator MCP
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=root
WorkingDirectory={BASE}/current
ExecStart={node}/bin/node {BASE}/current/server.mjs
Environment=OPS_CONFIG={CONFIG}/runtime.json
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=10
UMask=0077
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/zacks-ops-mcp.service").write_text(unit)
    connector = shutil.which("cloudflared")
    Path("/etc/systemd/system/cloudflared-ops-mcp.service").write_text(f"""[Unit]
Description=Dedicated Zacks operations MCP tunnel
After=network-online.target zacks-ops-mcp.service
Wants=network-online.target
[Service]
ExecStart={connector} tunnel --config {CONFIG}/tunnel.json --no-autoupdate --metrics 127.0.0.1:49394 run --token-file {token_file}
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
""")
    run(["systemctl", "daemon-reload"])
    try:
        run(["systemctl", "enable", "zacks-ops-mcp.service", "cloudflared-ops-mcp.service"])
        run(["systemctl", "restart", "zacks-ops-mcp.service"])
        for _ in range(30):
            try:
                report = health()
                if report.get("commit") == args.commit:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("runtime_not_ready")
        run(["systemctl", "restart", "cloudflared-ops-mcp.service"])
        return report
    except Exception:
        run(["systemctl", "stop", "zacks-ops-mcp.service", "cloudflared-ops-mcp.service"])
        if old_current and old_config:
            temp.symlink_to(old_current)
            os.replace(temp, BASE / "current")
            private_json(CONFIG / "runtime.json", old_config)
            run(["systemctl", "start", "zacks-ops-mcp.service", "cloudflared-ops-mcp.service"])
        raise


def install(args, value):
    connector_unit = Path("/etc/systemd/system/cloudflared-ops-mcp.service")
    existed = connector_unit.exists()
    old_current = (BASE / "current").resolve() if (BASE / "current").is_symlink() else None
    old_config = (
        json.loads((CONFIG / "runtime.json").read_text())
        if (CONFIG / "runtime.json").exists()
        else None
    )
    if existed:
        run(["systemctl", "stop", "cloudflared-ops-mcp.service"])
    activation_started = False
    try:
        if (
            existed
            and run(
                ["systemctl", "show", "zacks-ops-mcp.service", "--property=ActiveState", "--value"]
            ).strip()
            == "active"
        ):
            for _ in range(130):
                if health().get("activeOperations") == 0:
                    break
                time.sleep(1)
            else:
                raise RuntimeError("active_operations_not_drained")
        activation_started = True
        return activate(args, value)
    except Exception:
        if existed and not activation_started:
            run(["systemctl", "start", "cloudflared-ops-mcp.service"])
        elif existed and old_current and old_config:
            temp = BASE / "restore"
            unlink(temp)
            temp.symlink_to(old_current)
            os.replace(temp, BASE / "current")
            private_json(CONFIG / "runtime.json", old_config)
            run(["systemctl", "restart", "zacks-ops-mcp.service", "cloudflared-ops-mcp.service"])
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=["preflight", "credentials", "apply", "health", "withdraw"]
    )
    parser.add_argument("--commit", required=True)
    parser.add_argument("--staging", type=Path)
    parser.add_argument("--source-sha256")
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch("[a-f0-9]{40}", args.commit):
        raise ValueError("invalid_install_authority")
    if args.operation == "preflight":
        report = preflight()
    elif args.operation == "credentials":
        private_json(CONFIG / "cloudflare.json", json.load(sys.stdin))
        report = {"ok": True}
    elif args.operation == "apply":
        report = install(args, json.load(sys.stdin))
    elif args.operation == "withdraw":
        run(
            [
                "systemctl",
                "disable",
                "--now",
                "zacks-ops-mcp.service",
                "cloudflared-ops-mcp.service",
            ]
        )
        report = {"ok": True, "withdrawn": True}
    else:
        report = health()
        if report.get("commit") != args.commit:
            raise RuntimeError("runtime_identity_mismatch")
    print(json.dumps(report))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "errorClass": type(exc).__name__}))
        sys.exit(1)
