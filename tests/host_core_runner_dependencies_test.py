from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_runner_installs_and_smokes_health_tool_before_production_mutation():
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-host-core.yml").read_text())
    job = workflow["jobs"]["operate"]
    steps = job["steps"]
    names = [step.get("name", "") for step in steps]
    index = names.index("Install and validate runner operations dependencies")
    install = steps[index]
    assert "PyYAML==6.0.3" in install["run"]
    assert "scripts/webapp_production_health.py --help" in install["run"]
    assert "if" not in install
    assert "continue-on-error" not in install
    assert index < names.index("Configure SSH identity")
    assert index < names.index("Prepare exact remote commit")
    assert index < names.index("Operate host core")
    assert job["environment"] == "production"
    assert "Require successful CI for exact commit" in names


def test_health_cli_import_and_help_require_no_production_access():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/webapp_production_health.py"), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    assert "--expected-commit" in result.stdout
