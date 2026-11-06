from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import deploy_wechat_sender  # noqa: E402


def test_remote_failure_says_where_it_stopped_without_publishing_remote_text():
    evidence = deploy_wechat_sender.remote_failure_evidence(
        1,
        "sender-step: fetch_target\nprivate stdout\nsender-step: install_apply\n",
        "fatal: https://token@host.example/repo\n"
        "wechat-sender deploy: https://private.example failed\n"
        "wechat-sender deploy: service did not become ready\n"
        "root@10.0.0.1: permission denied\n",
    )

    assert evidence == {
        "stage": "sender_remote_failure",
        "exit_code": 1,
        "last_step": "install_apply",
        "install_message": "wechat-sender deploy: service did not become ready",
    }
    assert "private" not in str(evidence) and "token" not in str(evidence)


def test_remote_failure_without_markers_reports_the_ssh_exit_code():
    evidence = deploy_wechat_sender.remote_failure_evidence(255, "", "Connection closed by host\n")

    assert evidence["exit_code"] == 255
    assert evidence["last_step"] is None and evidence["install_message"] is None


def test_every_apply_step_is_marked_before_it_runs():
    script = deploy_wechat_sender.remote_script()
    order = [
        "step fetch_target",
        "step dependency_preflight",
        "step prepare_rollback",
        "step preserve_drift",
        "step checkout",
        "step install_preflight",
        "step install_apply",
        "step health",
    ]

    positions = [script.index(marker) for marker in order]
    assert positions == sorted(positions)
