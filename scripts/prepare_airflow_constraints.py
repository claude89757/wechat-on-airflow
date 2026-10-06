"""Apply the sole cryptography security exception to upstream Airflow constraints."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path


def patch_constraints(upstream: str, requirements: str) -> str:
    """Keep every upstream line except its one cryptography version pin."""
    pins = [line for line in requirements.splitlines() if line.startswith("cryptography==")]
    if len(pins) != 1:
        raise ValueError("Expected exactly one explicit cryptography security pin")
    lines = upstream.splitlines(keepends=True)
    indices = [i for i, line in enumerate(lines) if line.startswith("cryptography==")]
    if len(indices) != 1:
        raise ValueError("Expected exactly one upstream cryptography constraint")
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
