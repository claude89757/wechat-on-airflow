from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def rollback_shell() -> str:
    """Exercise the production shell, without importing operations dependencies."""
    tree = ast.parse((ROOT / "scripts/deploy_wechat_sender.py").read_text())
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "remote_script"
    )
    assignment = function.body[0]
    assert isinstance(assignment, ast.Assign)
    script = ast.literal_eval(assignment.value)
    return script.split("venv_identity_before=", 1)[1].split("trap rollback EXIT", 1)[0]


@pytest.mark.parametrize("phase", ["before_activation", "after_activation", "during_swap"])
def test_rollback_only_restores_environment_changed_by_this_attempt(tmp_path, phase):
    active = tmp_path / "venv"
    previous = tmp_path / "venv.previous"
    active.mkdir()
    previous.mkdir()
    (active / "release").write_text("current")
    (previous / "release").write_text("stale")
    service = tmp_path / "unit"
    service.write_text("original unit")
    calls = tmp_path / "calls"
    if phase == "before_activation":
        operation = ":"
    else:
        operation = 'rm -rf "$venv_dir.previous"; mv "$venv_dir" "$venv_dir.previous"'
        if phase == "after_activation":
            operation += '; mkdir "$venv_dir"; echo candidate > "$venv_dir/release"'
    script = (
        """set -eu
current_commit=original
legacy_backup=""
cleanup_bundle() { :; }
git() { :; }
systemctl() { printf '%s\\n' "$*" >> "$calls"; }
venv_identity_before="""
        + rollback_shell()
        + operation
        + "\nrollback 42\n"
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "venv_dir": str(active),
            "service_file": str(service),
            "install_dir": str(tmp_path),
            "calls": str(calls),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 42, result.stderr
    assert (active / "release").read_text() == "current"
    assert service.read_text() == "original unit"
    if phase == "before_activation":
        assert (previous / "release").read_text() == "stale"
        assert not calls.exists()
        assert not (tmp_path / "venv.failed").exists()
    else:
        assert not previous.exists()
        assert calls.read_text().splitlines() == [
            "daemon-reload",
            "restart wechat-sender.service",
        ]
        if phase == "after_activation":
            assert (tmp_path / "venv.failed/release").read_text().strip() == "candidate"


def test_health_checks_imported_dependencies_with_service_interpreter():
    source = (ROOT / "scripts/deploy_wechat_sender.py").read_text()
    health = source.split("health() {", 1)[1].split("device_state() {", 1)[0]
    assert "dependencies_ready=false" in health
    assert '"$venv_dir/bin/python" "$install_dir/sender_agent/verify_dependencies.py"' in health
    assert '"$install_dir/docker/sender/requirements.lock" >/dev/null 2>&1; then' in health
    assert 'and sys.argv[6] == "true"' in health
    assert '"dependencies_ready": sys.argv[6] == "true"' in health
