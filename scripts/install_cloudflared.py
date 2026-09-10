#!/usr/bin/env python3
"""Install the reviewed cloudflared client, verifying its upstream release digest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def install(destination: Path) -> None:
    config = json.loads((ROOT / "config/device-network.json").read_text())["cloudflared"]
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine())
    asset = f"linux-{arch}"
    if platform.system() != "Linux" or asset not in config:
        raise RuntimeError("cloudflared client platform is not pinned")
    expected = config[asset]
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == expected:
        destination.chmod(0o755)
        return
    url = f"https://github.com/cloudflare/cloudflared/releases/download/{config['version']}/cloudflared-{asset}"
    with urlopen(url, timeout=60) as response:
        data = response.read(64 * 1024 * 1024 + 1)
    if len(data) > 64 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("cloudflared release digest mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staged:
        temporary = Path(staged.name)
        try:
            staged.write(data)
            staged.flush()
            os.fsync(staged.fileno())
            temporary.chmod(0o755)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    install(parser.parse_args().destination)
