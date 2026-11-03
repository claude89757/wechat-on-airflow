"""Run a protected MCP preflight, apply and independent health in order."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def lifecycle(component: str, runner=subprocess.run) -> None:
    scripts = {
        "remote_ops": "scripts/deploy_remote_ops_mcp.py",
        "pi_mcp": "scripts/deploy_pi_appium_mcp.py",
    }
    for operation in ("preflight", "apply", "health"):
        runner(
            [sys.executable, scripts[component]],
            env={**os.environ, "OPERATION": operation},
            check=True,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=("remote_ops", "pi_mcp"))
    try:
        lifecycle(parser.parse_args().component)
    except subprocess.CalledProcessError:
        raise SystemExit(1) from None
