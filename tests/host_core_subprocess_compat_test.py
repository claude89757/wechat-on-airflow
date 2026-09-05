from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "host_core_production_subprocess_test",
    ROOT / "scripts" / "host_core_production.py",
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def python36_run(command, **kwargs):
    # CPython 3.6 tests keyword presence, not whether stdin's value is None.
    if kwargs.get("input") is not None and "stdin" in kwargs:
        raise ValueError("stdin and input arguments may not both be used.")
    return subprocess.CompletedProcess(command, 0, stdout="ready\n", stderr="")


@pytest.mark.parametrize("payload", [None, "", "test-only-bootstrap-token\n"])
def test_run_uses_exactly_one_input_mode(payload):
    environment = {"TEST_ONLY": "yes"}
    with patch.object(MODULE.subprocess, "run", side_effect=python36_run) as execute:
        result = MODULE.run(
            ["test-command"], check=False, capture=True, env=environment, input_text=payload
        )
    arguments = execute.call_args.kwargs
    assert result.returncode == 0
    assert arguments["cwd"] == str(ROOT)
    assert arguments["env"] is environment
    assert arguments["check"] is False
    assert arguments["universal_newlines"] is True
    assert arguments["stdout"] == subprocess.PIPE
    assert arguments["stderr"] == subprocess.PIPE
    if payload is None:
        assert arguments["stdin"] == subprocess.DEVNULL
        assert "input" not in arguments
    else:
        assert arguments["input"] == payload
        assert "stdin" not in arguments


@pytest.mark.parametrize("payload", [None, "", "test-only-input\n"])
def test_run_delivers_input_or_eof_to_real_child(payload):
    result = MODULE.run(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        capture=True,
        input_text=payload,
    )
    assert result.returncode == 0
    assert result.stdout == (payload or "")


def test_run_preserves_failure_propagation():
    command = [sys.executable, "-c", "raise SystemExit(7)"]
    with pytest.raises(subprocess.CalledProcessError) as error:
        MODULE.run(command, capture=True)
    assert error.value.returncode == 7
    assert MODULE.run(command, check=False, capture=True).returncode == 7


def test_secret_sync_passes_token_only_on_stdin_with_python36_contract():
    token = "test-only-bootstrap-token-not-a-secret"
    with (
        patch.object(MODULE, "assert_target"),
        patch.object(MODULE, "variable_get", return_value=token),
        patch.object(MODULE.subprocess, "run", side_effect=python36_run) as execute,
    ):
        result = MODULE.sync_secrets("a" * 40)
    assert result["secretSync"] == "complete"
    assert execute.call_count == 3
    staging, synchronization, validation = execute.call_args_list
    assert staging.kwargs["input"] == token + "\n"
    assert "stdin" not in staging.kwargs
    assert "-T" in staging.args[0]
    for call in (staging, synchronization, validation):
        assert token not in repr(call.args)
    for call in (synchronization, validation):
        assert call.kwargs["stdin"] == subprocess.DEVNULL
        assert "input" not in call.kwargs
    assert validation.kwargs["stdout"] == subprocess.PIPE
