from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "host_core_command_with_heartbeat.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("host_core_command_with_heartbeat", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TimeoutThenSuccess:
    returncode = 0

    def __init__(self) -> None:
        self.calls = 0
        self.killed = False

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        self.calls += 1
        if self.calls == 1:
            raise subprocess.TimeoutExpired(["fake"], timeout)
        return "child-out\n", "child-err\n"

    def kill(self) -> None:
        self.killed = True


class ImmediateFailure:
    returncode = 7

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        del timeout
        return "", "failure-detail\n"

    def kill(self) -> None:
        raise AssertionError("completed child must not be killed")


def test_timeout_emits_heartbeat_and_forwards_output(
    monkeypatch: Any, capsys: Any
) -> None:
    module = load_module()
    process = TimeoutThenSuccess()
    monkeypatch.setattr(module.subprocess, "Popen", lambda *args, **kwargs: process)

    result = module.run_with_heartbeat(["fake"], "migration", interval_seconds=1)

    captured = capsys.readouterr()
    assert result == 0
    assert process.calls == 2
    assert process.killed is False
    assert "host_core_command_heartbeat" in captured.err
    assert '"label": "migration"' in captured.err
    assert "child-out" in captured.out
    assert "child-err" in captured.err


def test_child_exit_status_is_preserved(monkeypatch: Any, capsys: Any) -> None:
    module = load_module()
    monkeypatch.setattr(
        module.subprocess,
        "Popen",
        lambda *args, **kwargs: ImmediateFailure(),
    )

    result = module.run_with_heartbeat(["fake"], "failure", interval_seconds=1)

    captured = capsys.readouterr()
    assert result == 7
    assert "failure-detail" in captured.err


def test_main_forwards_arguments_to_production_script(monkeypatch: Any) -> None:
    module = load_module()
    observed: dict[str, object] = {}

    def fake_run(command: list[str], label: str, interval_seconds: int = 20) -> int:
        observed.update(
            {"command": command, "label": label, "interval": interval_seconds}
        )
        return 0

    monkeypatch.setattr(module, "run_with_heartbeat", fake_run)

    assert module.main(["migrate-sql", "--target-commit", "a" * 40]) == 0
    assert observed["command"] == [
        module.sys.executable,
        str(module.HOST_CORE_SCRIPT),
        "migrate-sql",
        "--target-commit",
        "a" * 40,
    ]
    assert observed["label"] == "Host Core migrate-sql"
    assert observed["interval"] == 20
