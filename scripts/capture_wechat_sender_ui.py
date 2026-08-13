#!/usr/bin/env python3
from __future__ import annotations

import argparse
import struct
import subprocess
from pathlib import Path

import yaml
from _ops import REPO_ROOT, OpsError, sender_remote, ssh_command

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def remote_script() -> str:
    return r"""
set -eu
credential_dir="$1"
device_name="$(tr -d '\r\n' < "$credential_dir/wechat_allowed_device_name")"
test -n "$device_name"
test "$(adb -s "$device_name" get-state 2>/dev/null)" = "device"
exec adb -s "$device_name" exec-out screencap -p
"""


def capture_screenshot(output_path: Path) -> tuple[int, int]:
    runtime = yaml.safe_load(
        (REPO_ROOT / "config" / "runtime-target.yaml").read_text(encoding="utf-8")
    )
    sender = runtime["managed_services"]["wechat_sender"]
    remote = sender_remote()
    command = [
        *ssh_command(remote),
        "sudo",
        "-n",
        "bash",
        "-s",
        "--",
        str(sender["credential_directory"]),
    ]
    result = subprocess.run(
        command,
        input=remote_script().encode(),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise OpsError("sender UI screenshot capture failed")
    if not result.stdout.startswith(PNG_SIGNATURE) or len(result.stdout) < 24:
        raise OpsError("sender UI screenshot was not a valid PNG")

    width, height = struct.unpack(">II", result.stdout[16:24])
    if width < 100 or height < 100:
        raise OpsError("sender UI screenshot dimensions were invalid")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(result.stdout)
    return width, height


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture protected sender UI evidence.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    width, height = capture_screenshot(args.output)
    print(f"sender UI screenshot captured: width={width} height={height}")


if __name__ == "__main__":
    try:
        main()
    except OpsError as exc:
        print(f"capture-wechat-sender-ui: {exc}")
        raise SystemExit(1) from exc
