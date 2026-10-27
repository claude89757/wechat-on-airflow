from __future__ import annotations

import json
import shlex
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from tests.sender_preflight_test import remote_shell

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import deploy_wechat_sender as deploy  # noqa: E402


@pytest.mark.parametrize("operation", ["dry-run", "apply"])
@pytest.mark.parametrize(
    "failure", [None, "bundle_upload", "wheel_upload", "ssh", "remote", "cleanup"]
)
def test_runner_stages_verified_wheel_and_cleans_exact_paths_on_all_outcomes(
    monkeypatch, operation, failure
):
    events = []
    local_paths = []
    emitted = []
    remote = {"host": "sender.invalid", "port": "22", "username": "deployer"}
    monkeypatch.setattr(
        sys, "argv", ["deploy", "--operation", operation, "--target-commit", "a" * 40]
    )
    monkeypatch.setattr(deploy, "resolve_target_commit", lambda value: value)
    monkeypatch.setattr(deploy, "sender_remote", lambda: remote)
    monkeypatch.setattr(deploy, "emit", lambda value, output_format: emitted.append(value))

    def bundle(path):
        events.append("bundle_verified")
        path.write_bytes(b"verified bundle")
        local_paths.append(path)

    def download(path, lock_text):
        assert lock_text == "Pillow==13.0.0\n"
        events.append("wheel_verified")
        path.write_bytes(b"verified inert wheel")
        local_paths.append(path)

    def upload(path, selected_remote, remote_path):
        assert selected_remote == remote
        assert path.is_file()
        assert deploy.REMOTE_ARTIFACT_PATTERN.fullmatch(remote_path)
        label = "bundle_upload" if remote_path.endswith(".bundle") else "wheel_upload"
        events.append((label, remote_path))
        if failure == label:
            raise deploy.OpsError("PRIVATE partial transfer")

    def run(argv, **kwargs):
        if argv[:2] == ["git", "show"]:
            assert argv[-1] == "a" * 40 + ":docker/sender/requirements.lock"
            return subprocess.CompletedProcess(argv, 0, "Pillow==13.0.0\n", "")
        assert argv[0] == "ssh"
        if "rm" in argv:
            paths = argv[argv.index("--") + 1 :]
            events.append(("cleanup", paths))
            assert len(paths) == 2
            assert all(deploy.REMOTE_ARTIFACT_PATTERN.fullmatch(path) for path in paths)
            if failure in {"cleanup", "ssh"}:
                raise deploy.OpsError("PRIVATE cleanup transport")
            return subprocess.CompletedProcess(argv, 0, "", "")
        events.append(("remote_started", argv[-2:]))
        assert argv[-2].endswith(".bundle")
        assert argv[-1] == argv[-2].removesuffix(".bundle") + ".pillow.whl"
        assert argv[-1] in [
            event[1] for event in events if isinstance(event, tuple) and event[0] == "wheel_upload"
        ]
        assert kwargs["check"] is False
        if failure == "ssh":
            raise OSError("PRIVATE SSH failure")
        if failure == "remote":
            return subprocess.CompletedProcess(
                argv,
                1,
                json.dumps(
                    {
                        "stage": "sender_dependency_preflight",
                        "ok": False,
                        "failure_category": "candidate_staged_artifact_invalid",
                        "candidate_artifact_failure_kind": "sha256_mismatch",
                        "candidate_failure_phase": "staged_artifact_validation",
                        "candidate_staged_artifact_verified": False,
                    }
                ),
                "PRIVATE STDERR",
            )
        events.append("remote_finished")
        return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")

    monkeypatch.setattr(deploy, "create_deployment_bundle", bundle)
    monkeypatch.setattr(deploy, "download_wheel", download)
    monkeypatch.setattr(deploy, "upload_deployment_bundle", upload)
    monkeypatch.setattr(deploy, "run", run)
    if failure not in {None, "cleanup"}:
        with pytest.raises(deploy.OpsError) as stopped:
            deploy.main()
        assert "PRIVATE" not in str(stopped.value)
    else:
        deploy.main()
        assert emitted == [{"ok": True}]
        assert events[-2] == "remote_finished"
    assert events[:2] == ["bundle_verified", "wheel_verified"]
    assert events[-1][0] == "cleanup"
    assert not any(path.exists() for path in local_paths)
    if failure == "remote":
        assert emitted[0]["candidate_staged_artifact_verified"] is False
        assert emitted[0]["candidate_artifact_failure_kind"] == "sha256_mismatch"
    assert "PRIVATE" not in json.dumps(emitted)


def test_health_does_not_download_upload_or_require_an_artifact(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["deploy", "--operation", "health"])
    monkeypatch.setattr(deploy, "resolve_target_commit", lambda value: "a" * 40)
    monkeypatch.setattr(
        deploy,
        "sender_remote",
        lambda: {"host": "sender.invalid", "port": "22", "username": "deployer"},
    )
    monkeypatch.setattr(deploy, "emit", lambda *args: None)

    def forbidden(*args, **kwargs):
        raise AssertionError("health must not stage deployment files")

    monkeypatch.setattr(deploy, "download_wheel", forbidden)
    monkeypatch.setattr(deploy, "upload_deployment_bundle", forbidden)
    monkeypatch.setattr(deploy, "create_deployment_bundle", forbidden)
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        assert argv[-2:] == ["", ""]
        return subprocess.CompletedProcess(argv, 0, '{"ok":true}', "")

    monkeypatch.setattr(deploy, "run", run)
    deploy.main()
    assert len(calls) == 1


@pytest.mark.parametrize("reason", ["sha256_mismatch", "PRIVATE https://secret@host"])
def test_runner_rejects_unverified_download_before_any_upload(monkeypatch, reason):
    monkeypatch.setattr(sys, "argv", ["deploy", "--operation", "dry-run"])
    monkeypatch.setattr(deploy, "resolve_target_commit", lambda value: "a" * 40)
    monkeypatch.setattr(deploy, "sender_remote", lambda: {})
    files = []

    def create_bundle(path):
        files.append(path)
        path.touch()

    def download(path, lock_text):
        files.append(path)
        path.touch()
        raise deploy.ArtifactError(reason)

    def run(argv, **kwargs):
        assert argv[:2] == ["git", "show"]
        return subprocess.CompletedProcess(argv, 0, "Pillow==13.0.0\n", "")

    monkeypatch.setattr(deploy, "create_deployment_bundle", create_bundle)
    monkeypatch.setattr(deploy, "download_wheel", download)
    monkeypatch.setattr(deploy, "run", run)
    with pytest.raises(deploy.OpsError, match="sender wheel staging failed") as stopped:
        deploy.main()
    assert "PRIVATE" not in str(stopped.value)
    assert not any(path.exists() for path in files)


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["/tmp/unrelated"],
        ["/tmp/wechat-sender-" + "a" * 32 + ".bundle;touch /PRIVATE"],
        ["/tmp/wechat-sender-" + "a" * 31 + ".pillow.whl"],
    ],
)
def test_runner_cleanup_rejects_any_path_outside_its_exact_uuid_names(monkeypatch, paths):
    calls = []
    monkeypatch.setattr(deploy, "run", lambda *args, **kwargs: calls.append(args))
    deploy.cleanup_deployment_artifacts({}, paths)
    assert not calls


@pytest.mark.parametrize("exit_code", [0, 42])
def test_remote_exit_trap_removes_both_validated_artifacts(exit_code):
    transfer_id = uuid.uuid4().hex
    bundle = Path(f"/tmp/wechat-sender-{transfer_id}.bundle")
    wheel = Path(f"/tmp/wechat-sender-{transfer_id}.pillow.whl")
    header = remote_shell().split('current_commit=""', 1)[0]
    try:
        bundle.touch()
        wheel.touch()
        result = subprocess.run(
            ["bash", "-s", "--", "a" * 40, "dry-run", "unused", "unused", str(bundle), str(wheel)],
            input=header + f"\nexit {exit_code}\n",
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == exit_code, result.stderr
        assert not bundle.exists()
        assert not wheel.exists()
    finally:
        bundle.unlink(missing_ok=True)
        wheel.unlink(missing_ok=True)


def test_uploaded_artifact_survives_until_installer_finishes_and_health_is_independent(tmp_path):
    transfer_id = uuid.uuid4().hex
    bundle = Path(f"/tmp/wechat-sender-{transfer_id}.bundle")
    wheel = Path(f"/tmp/wechat-sender-{transfer_id}.pillow.whl")
    checkout = tmp_path / "checkout"
    (checkout / "scripts").mkdir(parents=True)
    calls = tmp_path / "installer-calls"
    installer = checkout / "scripts/install_wechat_sender.sh"
    installer.write_text(
        f"#!/bin/bash\nset -eu\ntest -f {shlex.quote(str(wheel))}\nprintf '%s\\n' \"$*\" >>{shlex.quote(str(calls))}\n"
    )
    installer.chmod(0o755)
    script = remote_shell()
    header = script.split('current_commit=""', 1)[0]
    tail = script[script.rindex('legacy_backup="$(preserve_reviewed_drift)"') :]
    body = (
        header
        + f"\nunit_backup={shlex.quote(str(tmp_path / 'backup'))}\n"
        + """
preserve_reviewed_drift() { :; }
git() { :; }
health() { test ! -e "$pillow_wheel_path"; test ! -e "$bundle_path"; printf 'healthy\n'; }
"""
        + tail
    )
    try:
        bundle.touch()
        wheel.touch()
        result = subprocess.run(
            [
                "bash",
                "-s",
                "--",
                "a" * 40,
                "apply",
                str(checkout),
                "unused",
                str(bundle),
                str(wheel),
            ],
            input=body,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "healthy"
        assert len(calls.read_text().splitlines()) == 2
        assert all(
            "--pillow-wheel " + str(wheel) in line for line in calls.read_text().splitlines()
        )
    finally:
        bundle.unlink(missing_ok=True)
        wheel.unlink(missing_ok=True)
