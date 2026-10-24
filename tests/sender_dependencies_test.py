from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from sender_agent.verify_dependencies import verify

ROOT = Path(__file__).resolve().parents[1]


def test_pillow_sender_pin_matches_runtime_lock():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    pins = [
        pin
        for pin in project["project"]["optional-dependencies"]["sender"]
        if pin.startswith("Pillow==")
    ]
    lock = (ROOT / "docker/sender/requirements.lock").read_text().splitlines()
    assert pins == ["Pillow==13.0.0"]
    assert [line for line in lock if line.startswith("Pillow==")] == pins


@pytest.mark.parametrize(
    ("version", "module_path", "lock", "error"),
    [
        ("12.3.0", "inside", "Pillow==13.0.0\n", "does not match"),
        ("13.0.0", "inside", "", "does not match"),
        ("13.0.0", "inside", "Pillow==13.0.0\nPillow==13.0.0\n", "does not match"),
        ("13.0.0", "/distribution/PIL/__init__.py", "Pillow==13.0.0\n", "interpreter prefix"),
    ],
)
def test_rejects_unlocked_or_distribution_pillow(tmp_path, version, module_path, lock, error):
    lock_path = tmp_path / "requirements.lock"
    lock_path.write_text(lock)
    pil = ModuleType("PIL")
    pil.__version__ = version
    pil.__file__ = (
        str(Path(sys.prefix) / "lib/PIL/__init__.py") if module_path == "inside" else module_path
    )
    pil.Image = ModuleType("PIL.Image")
    pil.ImageOps = ModuleType("PIL.ImageOps")
    with patch.dict(sys.modules, {"PIL": pil}), pytest.raises(RuntimeError, match=error):
        verify(lock_path)


def test_docker_and_systemd_execute_runtime_check_before_activation():
    dockerfile = (ROOT / "docker/sender/Dockerfile").read_text()
    assert "RUN python sender_agent/verify_dependencies.py requirements.lock" in dockerfile
    installer = (ROOT / "scripts/install_wechat_sender.sh").read_text()
    assert installer.index("verify_dependencies.py") < installer.index('mv "$next_venv"')
    assert installer.index("verify_dependencies.py") < installer.index("systemctl restart")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "/tmp/sender-dependency-check/bin/python sender_agent/verify_dependencies.py" in workflow


def test_rejects_wrong_python_version(tmp_path):
    pil = ModuleType("PIL")
    pil.Image = ModuleType("PIL.Image")
    pil.ImageOps = ModuleType("PIL.ImageOps")
    with patch.dict(sys.modules, {"PIL": pil}), patch("sys.version_info", (3, 11)):
        with pytest.raises(RuntimeError, match="Python 3.12"):
            verify(tmp_path / "not-read-before-version-check")
