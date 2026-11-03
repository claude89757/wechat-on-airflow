from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import shlex
import stat
import struct
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import sender_wheelhouse as artifact

ROOT = Path(__file__).resolve().parents[1]


def wheel_bytes(name, version, tag, requires=""):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as wheel:
        prefix = name.replace("-", "_") + "-" + version + ".dist-info/"
        wheel.writestr(
            prefix + "METADATA",
            f"Name: {name}\nVersion: {version}\nRequires-Python: >=3.11\n" + requires,
        )
        wheel.writestr(prefix + "WHEEL", "Wheel-Version: 1.0\nTag: " + tag + "\n")
    return output.getvalue()


def write_archive(path, files, fault=None):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for index, (filename, data) in enumerate(files.items()):
            info = zipfile.ZipInfo(filename)
            info.external_attr = (stat.S_IFREG | 0o600) << 16
            if index == 0:
                if fault == "traversal":
                    info.filename = "../" + filename
                elif fault == "absolute":
                    info.filename = "/" + filename
                elif fault == "symlink":
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                elif fault == "directory":
                    info.external_attr = (stat.S_IFDIR | 0o700) << 16
                elif fault == "compressed":
                    info.compress_type = zipfile.ZIP_DEFLATED
                elif fault == "extra":
                    info.extra = b"\xff\xff\x00\x00"
            archive.writestr(info, data)
            if fault == "duplicate" and index == 0:
                with pytest.warns(UserWarning):
                    archive.writestr(info, data)
        if fault == "additional":
            archive.writestr("unapproved.whl", b"PRIVATE")


@pytest.fixture
def staged(tmp_path, monkeypatch):
    files, records = {}, []
    for name, version, tag in (
        ("pure-pkg", "2.0.0", "py3-none-any"),
        ("native-pkg", "1.0.0", "cp311-cp311-linux_armv7l"),
    ):
        filename = name.replace("-", "_") + "-" + version + "-" + tag + ".whl"
        data = wheel_bytes(name, version, tag)
        files[filename] = data
        records.append(
            {
                "requirement": name + "==" + version,
                "filename": filename,
                "url": "https://files.pythonhosted.org/packages/approved/" + filename,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "tags": [tag],
            }
        )
    lock, manifest = tmp_path / "requirements.lock", tmp_path / "manifest.json"
    lock.write_text("\n".join(record["requirement"] for record in records) + "\n")
    manifest.write_text(
        json.dumps({"schema_version": 1, "target": artifact.TARGET, "wheels": records})
    )
    source, directory = tmp_path / "upload.zip", tmp_path / "private-wheels"
    write_archive(source, files)
    monkeypatch.setattr(
        artifact, "arm32_tags", lambda: {"py3-none-any", "cp311-cp311-linux_armv7l"}
    )
    return SimpleNamespace(
        source=source,
        directory=directory,
        lock=lock,
        manifest=manifest,
        files=files,
        records=records,
    )


def stage(value):
    return artifact.stage_wheelhouse(value.lock, value.manifest, str(value.source), value.directory)


def test_release_manifest_covers_every_exact_lock_and_both_native_packages():
    records = artifact.read_manifest(
        (ROOT / artifact.MANIFEST_PATH).read_text(),
        (ROOT / "docker/sender/requirements.lock").read_text(),
    )
    assert len(records) == 27
    assert sum(record["size"] for record in records) == 15_352_728
    native = {record["requirement"] for record in records if "py3-none-any" not in record["tags"]}
    assert native == {"Pillow==13.0.0", "pydantic_core==2.46.4"}


def test_private_archive_is_validated_after_copy_and_upload_can_change(staged):
    original = artifact.verify_archive

    def verify_private(path, records, directory, tags):
        assert path == staged.directory / artifact.ARCHIVE_NAME
        staged.source.write_bytes(b"changed upload")
        return original(path, records, directory, tags)

    with patch.object(artifact, "verify_archive", side_effect=verify_private):
        assert stage(staged) is True
    assert stat.S_IMODE(staged.directory.stat().st_mode) == 0o700
    assert {path.name for path in staged.directory.iterdir()} == set(staged.files)
    for filename, data in staged.files.items():
        assert (staged.directory / filename).read_bytes() == data
        assert stat.S_IMODE((staged.directory / filename).stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "fault",
    [
        "traversal",
        "absolute",
        "symlink",
        "directory",
        "compressed",
        "extra",
        "duplicate",
        "additional",
    ],
)
def test_archive_rejects_noncanonical_or_unapproved_members_before_install(staged, fault):
    write_archive(staged.source, staged.files, fault)
    with pytest.raises(artifact.ArtifactError, match="^archive_invalid$"):
        stage(staged)


def test_archive_central_directory_count_is_bounded_before_zipfile_allocations(staged):
    data = bytearray(staged.source.read_bytes())
    struct.pack_into("<H", data, len(data) - 12, 65535)
    staged.source.write_bytes(data)
    with patch.object(artifact.zipfile, "ZipFile", side_effect=AssertionError("must reject first")):
        with pytest.raises(artifact.ArtifactError, match="^archive_invalid$"):
            stage(staged)


@pytest.mark.parametrize("kind", ["missing", "symlink", "fifo", "oversize"])
def test_untrusted_upload_is_regular_nofollow_and_size_bounded(staged, kind):
    staged.source.unlink()
    if kind == "symlink":
        staged.source.symlink_to(staged.lock)
    elif kind == "fifo":
        os.mkfifo(staged.source)
    elif kind == "oversize":
        staged.source.write_bytes(b"x" * (sum(record["size"] for record in staged.records) + 2000))
    with pytest.raises(artifact.ArtifactError):
        stage(staged)
    assert not staged.directory.exists()


@pytest.mark.parametrize(
    "fault",
    [
        "missing_pin",
        "extra_pin",
        "duplicate_pin",
        "url_requirement",
        "version",
        "filename",
        "sha_type",
        "size_type",
        "url_host",
        "userinfo",
        "port",
        "tags",
        "target",
    ],
)
def test_manifest_is_exact_lock_closure_with_fixed_sources_and_strict_types(staged, fault):
    manifest = json.loads(staged.manifest.read_text())
    record = manifest["wheels"][0]
    if fault == "missing_pin":
        manifest["wheels"].pop()
    elif fault == "extra_pin":
        staged.lock.write_text(staged.lock.read_text() + "extra==3.0.0\n")
    elif fault == "duplicate_pin":
        staged.lock.write_text(staged.lock.read_text() + "pure_pkg==2.0.0\n")
    elif fault == "url_requirement":
        staged.lock.write_text("private @ https://PRIVATE.invalid\n")
    elif fault == "version":
        record["requirement"] = "pure-pkg==9.0.0"
    elif fault == "filename":
        record["filename"] = "../" + record["filename"]
    elif fault == "sha_type":
        record["sha256"] = True
    elif fault == "size_type":
        record["size"] = True
    elif fault == "url_host":
        record["url"] = record["url"].replace("files.pythonhosted.org", "PRIVATE.invalid")
    elif fault == "userinfo":
        record["url"] = record["url"].replace("https://", "https://@")
    elif fault == "port":
        record["url"] = record["url"].replace("files.pythonhosted.org", "files.pythonhosted.org:0")
    elif fault == "tags":
        record["tags"] = ["cp312-cp312-linux_armv7l"]
    elif fault == "target":
        manifest["target"]["python"] = "3.12"
    staged.manifest.write_text(json.dumps(manifest))
    with pytest.raises(artifact.ArtifactError, match="^(lock_mismatch|manifest_invalid)$"):
        stage(staged)


def test_each_extracted_wheel_hash_is_checked(staged):
    filename = next(iter(staged.files))
    staged.files[filename] = b"x" * len(staged.files[filename])
    write_archive(staged.source, staged.files)
    with pytest.raises(artifact.ArtifactError, match="^sha256_mismatch$"):
        stage(staged)


@pytest.mark.parametrize("fault", ["name", "version", "tags", "direct_url"])
def test_host_independently_checks_wheel_metadata_after_hash(staged, fault):
    record = staged.records[0]
    data = wheel_bytes(
        "wrong" if fault == "name" else "pure-pkg",
        "9.0.0" if fault == "version" else "2.0.0",
        "cp312-cp312-linux_armv7l" if fault == "tags" else "py3-none-any",
        "Requires-Dist: private @ https://PRIVATE.invalid/wheel\n" if fault == "direct_url" else "",
    )
    staged.files[record["filename"]] = data
    record.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
    staged.manifest.write_text(
        json.dumps({"schema_version": 1, "target": artifact.TARGET, "wheels": staged.records})
    )
    write_archive(staged.source, staged.files)
    with pytest.raises(artifact.ArtifactError, match="^metadata_mismatch$"):
        stage(staged)


def test_every_native_wheel_must_intersect_actual_tags(staged, monkeypatch):
    monkeypatch.setattr(
        artifact, "arm32_tags", lambda: {"py3-none-any", "cp311-cp311-linux_armv6l"}
    )
    with pytest.raises(artifact.ArtifactError, match="^tag_mismatch$"):
        stage(staged)


def test_linux_native_match_does_not_admit_an_incompatible_second_native_wheel(staged):
    # The real manifest has separate Pillow/linux and pydantic_core/manylinux wheels.
    tag = "cp311-cp311-manylinux_2_17_armv7l"
    filename = "second_native-3.0.0-" + tag + ".whl"
    data = wheel_bytes("second-native", "3.0.0", tag)
    staged.files[filename] = data
    staged.records.append(
        {
            "requirement": "second-native==3.0.0",
            "filename": filename,
            "url": "https://files.pythonhosted.org/packages/approved/" + filename,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "tags": [tag],
        }
    )
    staged.lock.write_text(staged.lock.read_text() + "second-native==3.0.0\n")
    staged.manifest.write_text(
        json.dumps({"schema_version": 1, "target": artifact.TARGET, "wheels": staged.records})
    )
    write_archive(staged.source, staged.files)
    with pytest.raises(artifact.ArtifactError, match="^tag_mismatch$"):
        stage(staged)


@pytest.mark.parametrize(
    "bits,platform,minor,expected",
    [
        (32, "linux_armv7l", 11, True),
        (64, "linux_armv7l", 11, False),
        (32, "linux_i686", 11, False),
        (64, "linux_aarch64", 12, False),
        (32, "linux_armv7l", 12, "tag_mismatch"),
    ],
)
def test_source_selection_requires_real_arm32_and_supported_minor(bits, platform, minor, expected):
    class Tag:
        def __init__(self):
            self.platform = platform

        def __str__(self):
            return f"cp3{minor}-cp3{minor}-" + platform

    module = ModuleType("pip._internal.utils.compatibility_tags")

    def supported():
        print("PRIVATE STDOUT")
        print("PRIVATE STDERR", file=sys.stderr)
        return [Tag()]

    module.get_supported = supported
    output, errors = io.StringIO(), io.StringIO()
    with (
        patch("struct.calcsize", return_value=bits // 8),
        patch("sys.version_info", (3, minor, 2)),
        patch.dict(sys.modules, {"pip._internal.utils.compatibility_tags": module}),
        contextlib.redirect_stdout(output),
        contextlib.redirect_stderr(errors),
    ):
        if expected == "tag_mismatch":
            with pytest.raises(artifact.ArtifactError, match="^tag_mismatch$"):
                artifact.arm32_tags()
        else:
            assert (artifact.arm32_tags() is not None) is expected
    assert not output.getvalue() and not errors.getvalue()


def test_nonarm_ignores_missing_artifact_and_creates_no_source(tmp_path):
    with patch.object(artifact, "arm32_tags", return_value=None):
        assert (
            artifact.stage_wheelhouse(
                tmp_path / "missing-lock", tmp_path / "missing-manifest", "", tmp_path / "wheels"
            )
            is False
        )
    assert list(tmp_path.iterdir()) == []


def test_runner_downloads_only_manifest_urls_and_verifies_before_packaging(staged, monkeypatch):
    calls = []

    def opened(url, timeout):
        calls.append((url, timeout))
        return io.BytesIO(staged.files[url.rsplit("/", 1)[-1]])

    monkeypatch.setattr(
        artifact.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=opened)
    )
    destination = staged.source.with_name("runner.zip")
    artifact.download_wheelhouse(destination, staged.lock.read_text(), staged.manifest.read_text())
    assert calls == [(record["url"], 60) for record in staged.records]
    staged.source = destination
    assert stage(staged) is True


@pytest.mark.parametrize("fault", ["sha256", "oversize"])
def test_runner_rejects_bad_download_before_packaging_with_a_bounded_read(
    staged, monkeypatch, fault
):
    reads = []
    record = staged.records[0]
    data = (
        b"x" * record["size"]
        if fault == "sha256"
        else staged.files[record["filename"]] + b"x" * 1000
    )

    class Response(io.BytesIO):
        def read(self, count):
            reads.append(count)
            return super().read(count)

    monkeypatch.setattr(
        artifact.urllib.request,
        "build_opener",
        lambda *args: SimpleNamespace(open=lambda *args, **kwargs: Response(data)),
    )
    with pytest.raises(artifact.ArtifactError, match="^(sha256_mismatch|size_mismatch)$"):
        artifact.download_wheelhouse(
            staged.source.with_name("runner.zip"),
            staged.lock.read_text(),
            staged.manifest.read_text(),
        )
    assert reads == [record["size"] + 1]


@pytest.mark.parametrize(
    "url", ["http://files.pythonhosted.org/file.whl", "https://PRIVATE.invalid/file.whl"]
)
def test_runner_refuses_source_or_tls_redirects(url):
    request = SimpleNamespace(full_url="https://files.pythonhosted.org/file.whl")
    with pytest.raises(artifact.ArtifactError, match="^download_failed$"):
        artifact.FixedSourceRedirect().redirect_request(request, None, 302, "", {}, url)


@pytest.mark.parametrize(
    "error", [artifact.ArtifactError("archive_invalid"), OSError("PRIVATE PATH")]
)
def test_helper_cli_only_emits_fixed_error_kind(staged, capsys, error):
    with (
        patch(
            "sys.argv",
            [
                "helper",
                "--lock",
                "/PRIVATE/lock",
                "--manifest",
                "/PRIVATE/manifest",
                "--artifact",
                "/PRIVATE/blob",
                "--directory",
                str(staged.directory),
            ],
        ),
        patch.object(artifact, "stage_wheelhouse", side_effect=error),
        pytest.raises(SystemExit) as stopped,
    ):
        artifact.main()
    assert stopped.value.code == 1
    output = capsys.readouterr()
    assert not output.out and output.err.strip() in artifact.FAILURE_KINDS
    assert "PRIVATE" not in output.err


@pytest.mark.parametrize(
    "verified,failure",
    [(False, None), (True, None), (True, "install"), (True, "checker"), (True, "artifact")],
)
def test_installer_offline_args_env_validation_and_cleanup(tmp_path, verified, failure):
    source = (ROOT / "scripts/install_wechat_sender.sh").read_text()
    block = source.split('"$SENDER_PYTHON" -m venv "$next_venv"\n', 1)[1].split(
        "# Validate before replacing the active environment", 1
    )[0]
    environment = tmp_path / "new"
    (environment / "bin").mkdir(parents=True)
    calls_file = tmp_path / "calls.jsonl"
    fake_python = environment / "bin/python"
    fake_python.write_text(
        f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
        + f"calls={str(calls_file)!r}\nfailure={failure!r}\n"
        + """
def record(argv, env=None):
    with open(calls, 'a') as output:
        output.write(json.dumps({'argv':argv,'pip_env':None if env is None else {key:value for key,value in env.items() if key.startswith('PIP_')}})+'\\n')
if sys.argv[1] == '-':
    def execve(path, argv, env):
        record(argv[1:],env)
        assert Path(argv[argv.index('--find-links')+1]).is_dir()
        raise SystemExit(1 if failure == 'install' else 0)
    os.execve=execve
    sys.argv=sys.argv[1:]
    exec(sys.stdin.read())
else:
    record(sys.argv[1:])
    if sys.argv[1].endswith('sender_wheelhouse.py'):
        if failure == 'artifact': raise SystemExit(1)
        Path(sys.argv[sys.argv.index('--directory')+1]).mkdir()
"""
        + f"        print({'true' if verified else 'false'!r})\n"
        + "    if sys.argv[1].endswith('verify_dependencies.py') and failure == 'checker': raise SystemExit(1)\n"
    )
    fake_python.chmod(0o755)
    checkout = tmp_path / "checkout"
    script = (
        f"set -euo pipefail\nnext_venv={shlex.quote(str(environment))}\nVENV_DIR={shlex.quote(str(tmp_path / 'active'))}\nINSTALL_DIR={shlex.quote(str(checkout))}\nWHEELHOUSE=/tmp/upload.zip\nfail() {{ exit 1; }}\n"
        + block
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env={
            **os.environ,
            "PIP_FIND_LINKS": "https://PRIVATE.invalid",
            "PIP_CONFIG_FILE": "/PRIVATE/config",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == (0 if failure is None else 1), result.stderr
    assert not list(tmp_path.glob("active.wheelhouse.*"))
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()]
    assert "--manifest" in calls[0]["argv"] and "--artifact" in calls[0]["argv"]
    installs = [call for call in calls if "install" in call["argv"]]
    if failure == "artifact":
        assert not installs
        return
    assert len(installs) == 1
    argv = installs[0]["argv"]
    assert ("--no-index" in argv) is verified
    assert ("--isolated" in argv) is verified
    assert ("--find-links" in argv) is verified
    assert ("--only-binary=:all:" in argv) is verified
    assert installs[0]["pip_env"] == ({"PIP_CONFIG_FILE": os.devnull} if verified else None)
    assert "--requirement" in argv and "--no-deps" not in argv
    if failure != "install":
        assert calls[-1]["argv"][0].endswith("verify_dependencies.py")
