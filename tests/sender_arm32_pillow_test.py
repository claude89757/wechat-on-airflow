from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shlex
import stat
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from scripts import sender_pillow_artifact as artifact
from tests.sender_preflight_test import diagnostic_helpers, safe_inventory

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def approved_fixture(tmp_path, monkeypatch):
    """A tiny inert wheel exercises validation without importing ARM machine code."""
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as wheel:
        wheel.writestr(
            "pillow-13.0.0.dist-info/METADATA",
            "Name: pillow\nVersion: 13.0.0\nRequires-Python: >=3.11\n",
        )
        wheel.writestr(
            "pillow-13.0.0.dist-info/WHEEL",
            "Wheel-Version: 1.0\nTag: cp311-cp311-linux_armv7l\n",
        )
    data = content.getvalue()
    monkeypatch.setattr(artifact, "WHEEL_SIZE", len(data))
    monkeypatch.setattr(artifact, "WHEEL_SHA256", hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(artifact, "arm32_tags", lambda: {artifact.WHEEL_TAG})
    source = tmp_path / "uploaded.blob"
    source.write_bytes(data)
    lock = tmp_path / "requirements.lock"
    lock.write_text("Pillow==13.0.0\nother==1.0.0\n")
    return source, lock, tmp_path / "private-wheels", data


def test_approved_artifact_identity_is_fixed():
    assert artifact.WHEEL_NAME == "pillow-13.0.0-cp311-cp311-linux_armv7l.whl"
    assert artifact.WHEEL_URL == "https://www.piwheels.org/simple/pillow/" + artifact.WHEEL_NAME
    assert artifact.WHEEL_SIZE == 1_317_640
    assert (
        artifact.WHEEL_SHA256 == "49eb06898ec42888e47c1cf1a97cb64b29af2b5d2773be60db1b1ecbbf92c3a6"
    )


def test_private_copy_is_hashed_after_copy_and_survives_upload_replacement(approved_fixture):
    source, lock, directory, data = approved_fixture
    original_verify = artifact.verify_wheel

    def verify_private(path):
        assert path == directory / artifact.WHEEL_NAME
        assert path.read_bytes() == data
        source.write_bytes(b"changed upload")
        original_verify(path)

    with patch.object(artifact, "verify_wheel", side_effect=verify_private):
        assert artifact.stage_wheel(lock, str(source), directory) is True
    assert (directory / artifact.WHEEL_NAME).read_bytes() == data
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE((directory / artifact.WHEEL_NAME).stat().st_mode) == 0o600
    assert [path.name for path in directory.iterdir()] == [artifact.WHEEL_NAME]


@pytest.mark.parametrize("changed_copy", [False, True])
def test_modified_upload_or_private_copy_fails_hash(approved_fixture, changed_copy):
    source, lock, directory, data = approved_fixture
    original_verify = artifact.verify_wheel

    def verify_private(path):
        if changed_copy:
            path.write_bytes(b"x" * len(data))
        original_verify(path)

    if not changed_copy:
        source.write_bytes(b"x" * len(data))
    with (
        patch.object(artifact, "verify_wheel", side_effect=verify_private),
        pytest.raises(artifact.ArtifactError, match="^sha256_mismatch$"),
    ):
        artifact.stage_wheel(lock, str(source), directory)


@pytest.mark.parametrize("source_kind", ["absent", "empty", "oversize", "symlink", "fifo"])
def test_missing_or_nonregular_or_oversize_artifact_fails_bounded(approved_fixture, source_kind):
    source, lock, directory, data = approved_fixture
    source.unlink()
    if source_kind == "empty":
        source.touch()
    elif source_kind == "oversize":
        source.write_bytes(data + b"x")
    elif source_kind == "symlink":
        source.symlink_to(lock)
    elif source_kind == "fifo":
        os.mkfifo(source)
    with pytest.raises(artifact.ArtifactError):
        artifact.stage_wheel(lock, str(source), directory)
    assert not directory.exists()


def test_empty_artifact_argument_on_arm32_fails(approved_fixture):
    _, lock, directory, _ = approved_fixture
    with pytest.raises(artifact.ArtifactError, match="^missing$"):
        artifact.stage_wheel(lock, "", directory)


@pytest.mark.parametrize(
    "lock_text",
    [
        "Pillow==12.0.0\n",
        "Pillow>=13.0.0\n",
        "Pillow @ https://PRIVATE.invalid/wheel\n",
        "Pillow==13.0.0\npillow==12.0.0\n",
    ],
)
def test_artifact_requires_the_exact_approved_lock_pin(approved_fixture, lock_text):
    source, lock, directory, _ = approved_fixture
    lock.write_text(lock_text)
    with pytest.raises(artifact.ArtifactError, match="^lock_mismatch$"):
        artifact.stage_wheel(lock, str(source), directory)
    assert not directory.exists()


@pytest.mark.parametrize(
    "bad_field", ["Name", "Version", "Requires-Python", "Tag", "Wheel-Version"]
)
def test_wheel_metadata_must_match_manifest_after_hash_validation(
    approved_fixture, monkeypatch, bad_field
):
    source, lock, directory, _ = approved_fixture
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as wheel:
        for name, fields in (
            ("METADATA", {"Name": "pillow", "Version": "13.0.0", "Requires-Python": ">=3.11"}),
            ("WHEEL", {"Wheel-Version": "1.0", "Tag": artifact.WHEEL_TAG}),
        ):
            if bad_field in fields:
                fields[bad_field] = "invalid"
            wheel.writestr(
                "pillow-13.0.0.dist-info/" + name,
                "".join(f"{key}: {value}\n" for key, value in fields.items()),
            )
    data = content.getvalue()
    source.write_bytes(data)
    monkeypatch.setattr(artifact, "WHEEL_SIZE", len(data))
    monkeypatch.setattr(artifact, "WHEEL_SHA256", hashlib.sha256(data).hexdigest())
    with pytest.raises(artifact.ArtifactError, match="^metadata_mismatch$"):
        artifact.stage_wheel(lock, str(source), directory)


@pytest.mark.parametrize("tag", ["cp312-cp312-linux_armv7l", "cp311-cp311-linux_armv6l"])
def test_exact_native_wheel_tag_is_required(approved_fixture, monkeypatch, tag):
    source, lock, directory, _ = approved_fixture
    monkeypatch.setattr(artifact, "arm32_tags", lambda: {tag})
    with pytest.raises(artifact.ArtifactError, match="^tag_mismatch$"):
        artifact.stage_wheel(lock, str(source), directory)


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
def test_source_selection_uses_actual_pointer_bits_and_pip_tags(bits, platform, expected):
    class Tag:
        def __init__(self):
            self.platform = platform

        def __str__(self):
            return "cp311-cp311-" + platform

    tags = ModuleType("pip._internal.utils.compatibility_tags")

    def supported():
        print("PRIVATE INDEX", file=sys.stderr)
        print("PRIVATE STDOUT")
        return [Tag()]

    tags.get_supported = supported
    output, errors = io.StringIO(), io.StringIO()
    with (
        patch("struct.calcsize", return_value=bits // 8),
        patch.dict(sys.modules, {"pip._internal.utils.compatibility_tags": tags}),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(errors),
    ):
        actual = artifact.arm32_tags()
    assert (actual is not None) is expected
    assert not output.getvalue()
    assert not errors.getvalue()


def test_nonarm_ignores_missing_artifact_and_leaves_no_source(tmp_path):
    with patch.object(artifact, "arm32_tags", return_value=None):
        assert artifact.stage_wheel(tmp_path / "absent-lock", "", tmp_path / "wheels") is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "error", [artifact.ArtifactError("sha256_mismatch"), OSError("PRIVATE PATH")]
)
def test_helper_cli_never_publishes_private_exception_or_path(tmp_path, capsys, error):
    with (
        patch(
            "sys.argv",
            [
                "helper",
                "--lock",
                "/PRIVATE/lock",
                "--artifact",
                "/PRIVATE/blob",
                "--directory",
                str(tmp_path),
            ],
        ),
        patch.object(artifact, "stage_wheel", side_effect=error),
        pytest.raises(SystemExit) as stopped,
    ):
        artifact.main()
    assert stopped.value.code == 1
    result = capsys.readouterr()
    assert not result.out
    assert result.err.strip() in artifact.FAILURE_KINDS
    assert "PRIVATE" not in result.err


def test_runner_download_is_exact_https_bounded_and_verified(approved_fixture):
    _, lock, directory, data = approved_fixture
    response = io.BytesIO(data)
    opener = type("Opener", (), {"open": lambda self, url, timeout: response})()
    with (
        patch.object(artifact.urllib.request, "build_opener", return_value=opener),
        patch.object(opener, "open", wraps=opener.open) as opened,
    ):
        artifact.download_wheel(directory, lock.read_text())
    opened.assert_called_once_with(artifact.WHEEL_URL, timeout=60)
    assert directory.read_bytes() == data


@pytest.mark.parametrize("fault", ["sha256", "oversize"])
def test_runner_rejects_bad_download_with_bounded_read(approved_fixture, fault):
    _, lock, destination, data = approved_fixture
    content = b"x" * len(data) if fault == "sha256" else data + b"x" * 100
    reads = []

    class Response(io.BytesIO):
        def read(self, size):
            reads.append(size)
            return super().read(size)

    opener = type("Opener", (), {"open": lambda self, url, timeout: Response(content)})()
    with (
        patch.object(artifact.urllib.request, "build_opener", return_value=opener),
        pytest.raises(artifact.ArtifactError, match="^(sha256_mismatch|size_mismatch)$"),
    ):
        artifact.download_wheel(destination, lock.read_text())
    assert reads == [len(data) + 1]


@pytest.mark.parametrize("url", ["http://www.piwheels.org/wheel", "https://PRIVATE.invalid/wheel"])
def test_runner_refuses_source_or_tls_redirects(url):
    with pytest.raises(artifact.ArtifactError, match="^download_failed$"):
        artifact.FixedSourceRedirect().redirect_request(None, None, 302, "", {}, url)


@pytest.mark.parametrize(
    "kind", ["sha256_mismatch", "missing", "PRIVATE /path https://secret@host"]
)
def test_preflight_publishes_only_fixed_artifact_failure_evidence(kind):
    namespace = diagnostic_helpers()
    with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 1, "PRIVATE", kind)):
        with pytest.raises(
            namespace["PreflightFailure"], match="^candidate_staged_artifact_invalid$"
        ):
            namespace["command"](["synthetic-helper"], "candidate_staged_artifact_invalid")
    expected = kind if kind in artifact.FAILURE_KINDS else "unclassified"
    assert namespace["report"] == {"candidate_artifact_failure_kind": expected}
    report = safe_inventory(
        {
            **namespace["report"],
            "candidate_failure_phase": "staged_artifact_validation",
            "candidate_staged_artifact_verified": False,
        }
    )
    assert report["candidate_artifact_failure_kind"] == expected
    assert report["candidate_failure_phase"] == "staged_artifact_validation"
    assert report["candidate_staged_artifact_verified"] is False
    assert "PRIVATE" not in json.dumps(report)
    assert "candidate_failure_phase" not in safe_inventory({"candidate_failure_phase": "PRIVATE"})
    assert (
        safe_inventory({"candidate_staged_artifact_verified": "true"})[
            "candidate_staged_artifact_verified"
        ]
        is False
    )


@pytest.mark.parametrize(
    "verified,failure",
    [(False, None), (True, None), (True, "install"), (True, "checker"), (True, "artifact")],
)
def test_installer_uses_only_private_wheel_directory_and_cleans_up(tmp_path, verified, failure):
    source = (ROOT / "scripts/install_wechat_sender.sh").read_text()
    block = source.split('"$SENDER_PYTHON" -m venv "$next_venv"\n', 1)[1].split(
        "# Validate before replacing the active environment", 1
    )[0]
    environment = tmp_path / "new"
    (environment / "bin").mkdir(parents=True)
    calls_file = tmp_path / "calls.jsonl"
    fake_python = environment / "bin/python"
    fake_python.write_text(
        f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
        f"with open({str(calls_file)!r}, 'a') as out: out.write(json.dumps(sys.argv[1:])+'\\n')\n"
        "if sys.argv[1].endswith('sender_pillow_artifact.py'):\n"
        f"    if {failure == 'artifact'}: raise SystemExit(1)\n"
        "    directory = Path(sys.argv[sys.argv.index('--directory')+1]); directory.mkdir()\n"
        f"    (directory / {artifact.WHEEL_NAME!r}).write_text('inert wheel')\n"
        f"    print({'true' if verified else 'false'!r})\n"
        "if 'install' in sys.argv and '--find-links' in sys.argv:\n"
        f"    assert (Path(sys.argv[-1]) / {artifact.WHEEL_NAME!r}).is_file()\n"
        f"if ('install' in sys.argv and {failure == 'install'}) or (sys.argv[1].endswith('verify_dependencies.py') and {failure == 'checker'}): raise SystemExit(1)\n"
    )
    fake_python.chmod(0o755)
    checkout = tmp_path / "checkout"
    script = (
        f"set -euo pipefail\nnext_venv={shlex.quote(str(environment))}\nVENV_DIR={shlex.quote(str(tmp_path / 'active'))}\nINSTALL_DIR={shlex.quote(str(checkout))}\nPILLOW_WHEEL=/tmp/uploaded.blob\n"
        "fail() { exit 1; }\n" + block
    )
    completed = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    assert completed.returncode == (0 if failure is None else 1), completed.stderr
    assert not list(tmp_path.glob("active.pillow.*"))
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    assert calls[0][0] == str(checkout / "scripts/sender_pillow_artifact.py")
    assert calls[0][calls[0].index("--artifact") + 1] == "/tmp/uploaded.blob"
    installs = [call for call in calls if call[:3] == ["-m", "pip", "install"]]
    if failure == "artifact":
        assert not installs
        return
    assert len(installs) == 1
    expected = [
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--only-binary=Pillow",
        "--requirement",
        str(checkout / "docker/sender/requirements.lock"),
    ]
    if verified:
        expected += ["--find-links", calls[0][-1]]
    assert installs[0] == expected
    if failure != "install":
        assert calls[-1] == [
            str(checkout / "sender_agent/verify_dependencies.py"),
            str(checkout / "docker/sender/requirements.lock"),
        ]
    for forbidden in (
        "https://www.piwheels",
        "--extra-index-url",
        "--trusted-host",
        "--platform",
        "--no-deps",
    ):
        assert forbidden not in block
