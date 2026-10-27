from __future__ import annotations

import contextlib
import io
import json
import shlex
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from tests.sender_preflight_test import preflight_python, safe_inventory

ROOT = Path(__file__).resolve().parents[1]
PILLOW_PAGE = "https://www.piwheels.org/simple/pillow/"


@pytest.mark.parametrize(
    "bits,arm32,inventory,expected",
    [
        (32, True, True, True),
        (64, True, True, False),
        (32, False, True, False),
        (64, False, True, False),
        (32, True, False, False),
    ],
)
def test_preflight_supplements_only_exact_pillow_on_verified_arm32(
    bits, arm32, inventory, expected
):
    source = preflight_python()
    block = source[
        source.index('        report["candidate_pillow_arm32_source"] =') : source.index(
            '        command([candidate_python, "-m", "pip", "check"]'
        )
    ]
    import textwrap

    calls = []
    report = {}
    lock = Path("/synthetic/requirements.lock")
    namespace = {
        "candidate": {
            "bits": bits,
            "pip_arm32_tags": arm32,
            "pip_tag_inventory_available": inventory,
        },
        "report": report,
        "candidate_python": "/synthetic/venv/bin/python",
        "pins": ["13.0.0"],
        "lock": lock,
        "command": lambda argv, *args, **kwargs: calls.append((argv, args, kwargs)),
    }
    exec(compile(textwrap.dedent(block), "preflight-pillow-install", "exec"), namespace)

    assert report == {"candidate_pillow_arm32_source": expected}
    assert len(calls) == (2 if expected else 1)
    full_lock = calls[-1][0]
    assert full_lock == [
        "/synthetic/venv/bin/python",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-cache-dir",
        "--only-binary=Pillow",
        "--requirement",
        str(lock),
    ]
    if expected:
        assert calls[0][0][-4:] == ["--no-deps", "--find-links", PILLOW_PAGE, "Pillow==13.0.0"]
        assert "--only-binary=Pillow" in calls[0][0]
        assert calls[0][1] == ("candidate_locked_install_failed", 300)
        assert calls[0][2] == {"install_lock": lock}
    assert safe_inventory(report)["candidate_pillow_arm32_source"] is expected


def installer_probe():
    source = (ROOT / "scripts/install_wechat_sender.sh").read_text()
    return source.split("<<'PILLOW_ARM32_PY'\n", 1)[1].split("\nPILLOW_ARM32_PY", 1)[0]


@pytest.mark.parametrize(
    "bits,platform,expected",
    [
        (32, "linux_armv7l", True),
        (32, "linux_armv6l", True),
        (64, "linux_armv7l", False),
        (32, "linux_i686", False),
        (64, "linux_aarch64", False),
    ],
)
def test_installer_source_guard_uses_interpreter_bits_and_real_pip_tags(
    tmp_path, bits, platform, expected
):
    lock = tmp_path / "requirements.lock"
    lock.write_text("Pillow==13.0.0\nother==1.0.0\n")
    tags = ModuleType("pip._internal.utils.compatibility_tags")

    def supported():
        print("PRIVATE INDEX", file=sys.stderr)
        print("PRIVATE STDOUT")
        return [SimpleNamespace(platform=platform)]

    tags.get_supported = supported
    output, errors = io.StringIO(), io.StringIO()
    with (
        patch("sys.argv", ["probe", str(lock)]),
        patch("struct.calcsize", return_value=bits // 8),
        patch.dict(sys.modules, {"pip._internal.utils.compatibility_tags": tags}),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(errors),
    ):
        exec(compile(installer_probe(), "installer-arm32-source", "exec"), {})
    assert output.getvalue().strip() == ("Pillow==13.0.0" if expected else "")
    assert not errors.getvalue()


@pytest.mark.parametrize(
    "lock_text",
    [
        "Pillow>=13.0.0\n",
        "Pillow @ https://PRIVATE.invalid/wheel\n",
        "Pillow==13.0.0\nPillow==12.0.0\n",
    ],
)
def test_installer_arm32_bootstrap_requires_one_exact_lock_pin(tmp_path, lock_text):
    lock = tmp_path / "requirements.lock"
    lock.write_text(lock_text)
    tags = ModuleType("pip._internal.utils.compatibility_tags")
    tags.get_supported = lambda: [SimpleNamespace(platform="linux_armv7l")]
    output = io.StringIO()
    with (
        patch("sys.argv", ["probe", str(lock)]),
        patch("struct.calcsize", return_value=4),
        patch.dict(sys.modules, {"pip._internal.utils.compatibility_tags": tags}),
        contextlib.redirect_stdout(output),
        pytest.raises(SystemExit, match="^Pillow must have one exact locked version$"),
    ):
        exec(compile(installer_probe(), "installer-arm32-source", "exec"), {})
    assert not output.getvalue()


@pytest.mark.parametrize("use_arm32_source", [False, True])
def test_installer_keeps_other_packages_on_the_original_full_lock_policy(
    tmp_path, use_arm32_source
):
    source = (ROOT / "scripts/install_wechat_sender.sh").read_text()
    block = source.split('"$SENDER_PYTHON" -m venv "$next_venv"\n', 1)[1].split(
        "# Validate before replacing the active environment", 1
    )[0]
    environment = tmp_path / "new"
    (environment / "bin").mkdir(parents=True)
    calls_file = tmp_path / "calls.jsonl"
    fake_python = environment / "bin/python"
    pin = "Pillow==13.0.0" if use_arm32_source else ""
    fake_python.write_text(
        f"#!{sys.executable}\nimport json,sys\n"
        f"with open({str(calls_file)!r}, 'a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')\n"
        f"if sys.argv[1] == '-': print({pin!r})\n"
    )
    fake_python.chmod(0o755)
    checkout = tmp_path / "checkout"
    script = (
        f"set -euo pipefail\nnext_venv={shlex.quote(str(environment))}\nINSTALL_DIR={shlex.quote(str(checkout))}\n"
        + block
    )
    completed = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    installs = [call for call in calls if call[:3] == ["-m", "pip", "install"]]
    assert len(installs) == (2 if use_arm32_source else 1)
    assert installs[-1] == [
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--only-binary=Pillow",
        "--requirement",
        str(checkout / "docker/sender/requirements.lock"),
    ]
    if use_arm32_source:
        assert installs[0][-4:] == ["--no-deps", "--find-links", PILLOW_PAGE, "Pillow==13.0.0"]
        assert "--only-binary=Pillow" in installs[0]
    assert calls[-1] == [
        str(checkout / "sender_agent/verify_dependencies.py"),
        str(checkout / "docker/sender/requirements.lock"),
    ]
    assert "--extra-index-url" not in source
    assert "--trusted-host" not in source
    assert "--platform" not in source
