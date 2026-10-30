"""Protected, additive Pi installation. Runtime secrets enter on stdin only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

BASE = Path("/opt/pi-appium-mcp")
CONFIG = Path("/etc/pi-appium-mcp")
NODE_SHA = "c9057c6a3b8fbb9651ed115c1e96d4a7281b7b9c9ca89fa05865c98ed7ffd437"
NODE_DIR = "node-v22.23.4-linux-armv7l"
EXISTING = ("wechat-sender.service", "zacks-agent.service", "cloudflared-dsh.service")


def run(argv, *, timeout=60, env=None, cwd=None):
    completed = subprocess.run(
        argv, capture_output=True, timeout=timeout, check=False, env=env, cwd=cwd
    )
    if completed.returncode:
        raise RuntimeError("command_failed")
    return completed.stdout.decode()


def health():
    for unit in EXISTING:
        run(["systemctl", "is-active", "--quiet", unit])
    for port, path in ((6001, "/status"), (6002, "/status"), (7001, "/healthz"), (7001, "/readyz")):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("existing_health_failed")


def unpack(archive, destination, *, trusted_links=False):
    with tarfile.open(archive) as handle:
        # Source/cache bundles contain no links; Node's known archive does.
        for member in handle.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.isdev():
                raise ValueError("unsafe_archive")
            if member.issym() or member.islnk():
                if not trusted_links:
                    raise ValueError("unsafe_archive_link")
                target = (destination / path.parent / member.linkname).resolve()
                if not target.is_relative_to(destination.resolve()):
                    raise ValueError("unsafe_archive_link")
        if hasattr(tarfile, "data_filter"):
            handle.extractall(destination, filter="data")
        else:
            handle.extractall(destination)


def private_json(path, value):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def verify_private_write(candidate):
    probe = candidate / ".private-write-probe.json"
    private_json(probe, {"probe": True})
    if probe.stat().st_mode & 0o777 != 0o600 or json.loads(probe.read_text()) != {"probe": True}:
        raise RuntimeError("private_configuration_probe_failed")
    probe.unlink()


def verify_source(candidate):
    required = (
        "server.mjs",
        "guard.mjs",
        "lock-holder.py",
        "smoke.mjs",
        "package.json",
        "package-lock.json",
        ".npmrc",
        "pi-appium-mcp.service",
        "test/guard.test.mjs",
        "test/transport.test.mjs",
    )
    if not all((candidate / name).is_file() for name in required):
        raise ValueError("incomplete_source_bundle")


def device_config():
    path = CONFIG / "devices.json"
    if path.exists():
        return json.loads(path.read_text())
    lines = run(["adb", "devices"]).splitlines()
    serials = [
        row.split()[0] for row in lines if len(row.split()) == 2 and row.split()[1] == "device"
    ]
    # Keep the existing production phone first, even if ADB enumeration changes.
    sender_serial = (
        Path("/etc/wechat-sender/credentials/wechat_allowed_device_name").read_text().strip()
    )
    if sender_serial not in serials or len(serials) > 2:
        raise RuntimeError("device_mapping_requires_review")
    serials = [sender_serial] + [serial for serial in serials if serial != sender_serial]
    return {
        "devices": [
            {
                "alias": f"phone_{i + 1}",
                "serial": serial,
                "appiumUrl": f"http://127.0.0.1:{6002 - i}",
                "systemPort": 8200 + i,
            }
            for i, serial in enumerate(serials)
        ]
    }


def atomic_link(target, path):
    temporary = path.with_suffix(".pending")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(target)
    temporary.replace(path)


def is_active(unit):
    return (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            capture_output=True,
            timeout=10,
            check=False,
        ).returncode
        == 0
    )


def drain_control():
    if not is_active("pi-appium-mcp.service"):
        return False
    tunnel_was_active = is_active("cloudflared-appium-mcp.service")
    if tunnel_was_active:
        run(["systemctl", "stop", "cloudflared-appium-mcp.service"])
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            report = json.loads(
                run([str(BASE / "node/bin/node"), str(BASE / "current/smoke.mjs")], timeout=15)
            )
            count = report.get("activePhoneSessions")
            if report.get("ok") is not True or type(count) is not int or count < 0:
                raise RuntimeError("mcp_session_state_unknown")
            if count == 0:
                return tunnel_was_active
            time.sleep(2)
        raise RuntimeError("mcp_control_not_idle")
    except Exception:
        if tunnel_was_active:
            run(["systemctl", "start", "cloudflared-appium-mcp.service"])
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=("preflight", "apply", "health", "credentials", "withdraw", "rollback")
    )
    parser.add_argument("--commit", required=True)
    parser.add_argument("--staging", type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0 or not re.fullmatch(r"[0-9a-f]{40}", args.commit):
        raise ValueError("root_and_exact_commit_required")
    health()
    if args.operation == "rollback":
        tunnel_was_active = drain_control()
        run(["systemctl", "stop", "pi-appium-mcp.service"])
        previous = BASE / "previous"
        if previous.exists():
            atomic_link(previous.resolve(), BASE / "current")
            shutil.copyfile(
                BASE / "current/pi-appium-mcp.service", "/etc/systemd/system/pi-appium-mcp.service"
            )
            run(["systemctl", "daemon-reload"])
            run(["systemctl", "start", "pi-appium-mcp.service"])
            report = json.loads(run([str(BASE / "node/bin/node"), str(BASE / "current/smoke.mjs")]))
            if not report.get("ok"):
                raise RuntimeError("rollback_health_failed")
            if tunnel_was_active:
                run(["systemctl", "start", "cloudflared-appium-mcp.service"])
        else:
            run(["systemctl", "disable", "pi-appium-mcp.service"])
            if Path("/etc/systemd/system/cloudflared-appium-mcp.service").exists():
                run(["systemctl", "disable", "--now", "cloudflared-appium-mcp.service"])
        health()
        return {"ok": True, "rolledBack": True, "previousReleaseAvailable": previous.exists()}
    if args.operation == "withdraw":
        drain_control()
        run(
            [
                "systemctl",
                "disable",
                "--now",
                "cloudflared-appium-mcp.service",
                "pi-appium-mcp.service",
            ]
        )
        health()
        return {"ok": True, "withdrawn": True}
    if args.operation == "credentials":
        value = json.load(sys.stdin)
        required = {
            "tunnel_token",
            "access_client_id",
            "access_client_secret",
            "tunnel_id",
            "app_id",
            "token_id",
        }
        if set(value) != required or not all(isinstance(v, str) and v for v in value.values()):
            raise ValueError("invalid_credentials")
        if (CONFIG / "cloudflare.json").exists():
            raise ValueError("credentials_already_provisioned")
        private_json(CONFIG / "cloudflare.json", value)
        token_path = CONFIG / "tunnel_token"
        token_path.write_text(value["tunnel_token"])
        token_path.chmod(0o600)
        tunnel_config = CONFIG / "tunnel.yml"
        tunnel_config.write_text("{}\n")
        tunnel_config.chmod(0o600)
        connector = shutil.which("cloudflared")
        if not connector:
            raise RuntimeError("cloudflared_missing")
        unit = f"""[Unit]
Description=Dedicated protected Pi Appium MCP tunnel
After=network-online.target pi-appium-mcp.service
Wants=network-online.target
[Service]
User=pi-appium-mcp
Group=pi-appium-mcp
LoadCredential=tunnel_token:/etc/pi-appium-mcp/tunnel_token
LoadCredential=tunnel_config:/etc/pi-appium-mcp/tunnel.yml
ExecStart={connector} tunnel --config %d/tunnel_config --no-autoupdate run --token-file %d/tunnel_token
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
"""
        Path("/etc/systemd/system/cloudflared-appium-mcp.service").write_text(unit)
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", "cloudflared-appium-mcp.service"])
        return {"ok": True, "credentialsStored": True}
    if args.operation == "health":
        if (BASE / "current" / "release.txt").read_text().strip() != args.commit:
            raise ValueError("release_mismatch")
        run(["systemctl", "is-active", "--quiet", "pi-appium-mcp.service"])
        return json.loads(run([str(BASE / "node/bin/node"), str(BASE / "current/smoke.mjs")]))

    if not args.staging or not args.staging.is_dir():
        raise ValueError("staging_required")
    if shutil.disk_usage("/opt").free < 2_000_000_000:
        raise RuntimeError("insufficient_candidate_disk_space")
    archive = args.staging / "node.tar.xz"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != NODE_SHA:
        raise ValueError("node_digest_mismatch")
    BASE.mkdir(mode=0o755, exist_ok=True)
    try:
        pwd.getpwnam("pi-appium-mcp")
    except KeyError:
        run(
            [
                "useradd",
                "--system",
                "--home-dir",
                "/var/lib/pi-appium-mcp",
                "--shell",
                "/usr/sbin/nologin",
                "pi-appium-mcp",
            ]
        )
    run(["usermod", "--append", "--groups", "wechat-sender", "pi-appium-mcp"])
    node = BASE / NODE_DIR
    if not node.exists():
        unpack(archive, BASE, trusted_links=True)
    if run([str(node / "bin/node"), "-p", "process.arch"]).strip() != "arm":
        raise ValueError("wrong_node_architecture")
    candidate = Path(tempfile.mkdtemp(prefix=f"candidate-{args.commit[:12]}-", dir=BASE))
    unpack(args.staging / "source.tar.gz", candidate)
    verify_source(candidate)
    verify_private_write(candidate)
    unpack(args.staging / "cache.tar.gz", candidate / "cache")
    environment = {
        "PATH": f"{node}/bin:/usr/local/bin:/usr/bin:/bin",
        "HOME": str(candidate),
        "npm_config_cache": str(candidate / "cache"),
        "npm_config_offline": "true",
    }
    run(
        [
            str(node / "bin/npm"),
            "ci",
            "--ignore-scripts",
            "--omit=optional",
            "--no-audit",
            "--no-fund",
        ],
        cwd=candidate,
        env=environment,
        timeout=600,
    )
    run(
        [str(node / "bin/node"), "--test", "test/guard.test.mjs", "test/transport.test.mjs"],
        cwd=candidate,
        env=environment,
        timeout=60,
    )
    shutil.rmtree(candidate / "cache")
    (candidate / "release.txt").write_text(args.commit + "\n")
    if args.operation == "preflight":
        shutil.rmtree(candidate)
        health()
        return {"ok": True, "candidateVerified": True, "applied": False, "externalTestSends": 0}
    devices = device_config()
    candidate.chmod(0o755)
    private_json(CONFIG / "devices.json", devices)
    state = Path("/var/lib/pi-appium-mcp")
    state.mkdir(mode=0o700, exist_ok=True)
    shutil.chown(state, "pi-appium-mcp", "pi-appium-mcp")
    previous = (BASE / "current").resolve() if (BASE / "current").exists() else None
    unit_path = Path("/etc/systemd/system/pi-appium-mcp.service")
    previous_unit = unit_path.read_bytes() if unit_path.exists() else None
    if previous:
        atomic_link(previous, BASE / "previous")
    tunnel_was_active = drain_control()
    try:
        atomic_link(node, BASE / "node")
        atomic_link(candidate, BASE / "current")
        shutil.copyfile(candidate / "pi-appium-mcp.service", unit_path)
        run(["systemctl", "daemon-reload"])
        run(["systemctl", "enable", "--now", "pi-appium-mcp.service"])
        run(["systemctl", "restart", "pi-appium-mcp.service"])
        for _ in range(20):
            try:
                report = json.loads(
                    run([str(node / "bin/node"), str(candidate / "smoke.mjs")], timeout=15)
                )
                if report.get("ok"):
                    health()
                    return {**report, "applied": True, "commit": args.commit}
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError("candidate_health_failed")
    except Exception:
        run(["systemctl", "stop", "pi-appium-mcp.service"])
        if previous and previous_unit:
            atomic_link(previous, BASE / "current")
            unit_path.write_bytes(previous_unit)
            run(["systemctl", "daemon-reload"])
            run(["systemctl", "start", "pi-appium-mcp.service"])
            if tunnel_was_active:
                run(["systemctl", "start", "cloudflared-appium-mcp.service"])
        health()
        raise


if __name__ == "__main__":
    try:
        print(json.dumps(main(), sort_keys=True))
    except Exception as exc:
        print(json.dumps({"ok": False, "errorClass": type(exc).__name__, "externalTestSends": 0}))
        raise SystemExit(1) from None
