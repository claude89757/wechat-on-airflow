from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import _ops  # noqa: E402
import deploy_wechat_sender as deploy  # noqa: E402

REMOTE = {"host": "sender.invalid", "port": "2222", "username": "deployer"}


def fake_ssh(monkeypatch, codes):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, codes.pop(0) if codes else 0, b"", b"PRIVATE")

    monkeypatch.setattr(_ops.subprocess, "run", run)
    return calls


def control_path() -> str:
    command = _ops.ssh_command(REMOTE)
    return next(item for item in command if item.startswith("ControlPath="))


def test_without_a_shared_connection_commands_are_unchanged():
    assert not any("Control" in item for item in _ops.ssh_command(REMOTE))
    assert _ops.ssh_options() == []


def test_dropped_connections_are_retried_then_every_call_reuses_one(monkeypatch):
    calls = fake_ssh(monkeypatch, [255, 255, 0])
    pauses = []

    with _ops.shared_ssh_connection(REMOTE, sleep=pauses.append):
        control = control_path()
        assert control in _ops.ssh_options()[1]
        assert control in _ops.ssh_command(REMOTE)
        directory = Path(control.removeprefix("ControlPath=")).parent
        assert directory.is_dir()

    assert pauses == [3, 6]
    probes = [call for call in calls if call[-1] == "true"]
    assert len(probes) == 3 and all("ControlMaster=auto" in call for call in probes)
    assert calls[-1][:3] == ["ssh", "-O", "exit"]
    assert not directory.exists()
    assert _ops.ssh_options() == []


def test_only_opening_the_connection_retries_never_a_remote_command(monkeypatch):
    calls = fake_ssh(monkeypatch, [0])

    with _ops.shared_ssh_connection(REMOTE):
        pass

    assert [call[-1] for call in calls if call[0] == "ssh" and "-O" not in call] == ["true"]


def test_a_real_failure_is_not_retried(monkeypatch):
    calls = fake_ssh(monkeypatch, [1])

    with pytest.raises(_ops.OpsError, match="exit code 1"):
        with _ops.shared_ssh_connection(REMOTE, sleep=lambda seconds: pytest.fail("retried")):
            pytest.fail("entered")

    assert len(calls) == 1
    assert _ops.ssh_options() == []


def test_giving_up_names_neither_host_nor_remote_output(monkeypatch):
    calls = fake_ssh(monkeypatch, [255] * 8)

    with pytest.raises(_ops.OpsError, match="after 8 attempts") as error:
        with _ops.shared_ssh_connection(REMOTE, sleep=lambda seconds: None):
            pytest.fail("entered")

    assert len(calls) == 8
    assert not any(text in str(error.value) for text in ("sender.invalid", "deployer", "PRIVATE"))
    assert _ops.ssh_options() == []


def test_scp_uploads_ride_the_shared_connection(monkeypatch, tmp_path):
    fake_ssh(monkeypatch, [0])
    uploads = []
    monkeypatch.setattr(deploy, "run", lambda command: uploads.append(command))

    with _ops.shared_ssh_connection(REMOTE):
        deploy.upload_deployment_bundle(tmp_path / "bundle", REMOTE, "/tmp/bundle")
        assert control_path() in uploads[0]

    deploy.upload_deployment_bundle(tmp_path / "bundle", REMOTE, "/tmp/bundle")
    assert not any("ControlPath" in item for item in uploads[1])


def test_the_sender_deploy_holds_one_connection_around_all_of_its_work():
    source = (ROOT / "scripts/deploy_wechat_sender.py").read_text(encoding="utf-8")
    main = source[source.index("def main()") :]

    assert main.index("shared_ssh_connection(remote)") < main.index("create_deployment_bundle(")
    assert main.index("shared_ssh_connection(remote)") < main.index("cleanup_deployment_artifacts(")
