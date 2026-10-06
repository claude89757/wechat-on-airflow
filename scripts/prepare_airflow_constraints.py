"""Apply the bounded cryptography compatibility exceptions to upstream Airflow constraints."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

SECURITY_PINS = ("cryptography", "gcloud-aio-auth", "pyOpenSSL")


def patch_constraints(upstream: str, requirements: str) -> str:
    """Preserve upstream constraints outside the reviewed security dependency set."""
    lines = upstream.splitlines(keepends=True)
    for package in SECURITY_PINS:
        prefix = f"{package}=="
        pins = [line for line in requirements.splitlines() if line.startswith(prefix)]
        if len(pins) != 1:
            raise ValueError(f"Expected exactly one explicit {package} security pin")
        indices = [i for i, line in enumerate(lines) if line.startswith(prefix)]
        if len(indices) != 1:
            raise ValueError(f"Expected exactly one upstream {package} constraint")
        index = indices[0]
        ending = "\r\n" if lines[index].endswith("\r\n") else "\n"
        lines[index] = pins[0] + ending
    return "".join(lines)


def main() -> None:
    url, requirements_path, output_path = sys.argv[1:]
    with urllib.request.urlopen(url, timeout=60) as response:
        upstream = response.read().decode("utf-8")
    patched = patch_constraints(upstream, Path(requirements_path).read_text())
    Path(output_path).write_text(patched)


if __name__ == "__main__":
    main()
