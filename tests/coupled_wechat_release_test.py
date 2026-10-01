"""Regression for production incident #226: ready Sender, incompatible consumer."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def guard():
    plan = types.ModuleType("release_plan")
    plan.resolve_commit = lambda ref: "a" * 40
    plan.previous_release_commit = lambda target: "b" * 40
    plan.diff_files = lambda base, head: ["sender_agent/app.py"]
    spec = importlib.util.spec_from_file_location(
        "coupled_scope_under_test", ROOT / "scripts/host_core_release_scope.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"release_plan": plan}):
        spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "path",
    [
        "src/wechat_airflow/host_core/wechat_worker.py",
        "sender_agent/app.py",
        "sender_agent/device_lease.py",
        "wechat_sender/operator.py",
        "docker/sender/requirements.lock",
        "deploy/systemd/wechat-sender.service",
        "docker-compose.sender.yml",
        "scripts/install_wechat_sender.sh",
        "scripts/deploy_wechat_sender.py",
        "scripts/preserve_sender_legacy_patch.py",
    ],
)
def test_sender_and_consumer_changes_require_coordinated_release(guard, path):
    assert guard.requires_host_core([path])


@pytest.mark.parametrize(
    "path",
    [
        "webapp/src/CourtStudio.tsx",
        "docs/wechat-sender-service.md",
        "tests/sender_device_lease_test.py",
        "dags/szw_tennis_court.py",
    ],
)
def test_unrelated_scopes_remain_independent(guard, path):
    assert not guard.requires_host_core([path])


@pytest.mark.parametrize("scope", ["auto", "sender", "airflow", "webapp", "control"])
def test_partial_sender_release_is_rejected_before_deploy(guard, monkeypatch, scope):
    monkeypatch.setattr(sys, "argv", ["scope", "--scope", scope])
    with pytest.raises(SystemExit) as error:
        guard.main()
    assert error.value.code == 2


def test_full_lifecycle_is_allowed(guard, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["scope", "--scope", "all"])
    guard.main()


def test_incident_inventory_preserves_history_and_never_reads_message_content():
    import ast

    tree = ast.parse((ROOT / "scripts/device_network_preflight.py").read_text())
    probe = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "HOST_PROBE" for target in node.targets
        )
    )
    compile(probe, "host_probe", "exec")
    queue_section = probe.split("# Diagnose the authoritative queue", 1)[1].split(
        "from wechat_airflow.host_core.health", 1
    )[0]
    assert "SET TRANSACTION READ ONLY" in queue_section
    assert "SET LOCAL statement_timeout = '5s'" in queue_section
    assert '"allHistory"' in queue_section
    assert '"last24Hours"' in queue_section
    assert "sender_not_ready" in queue_section
    assert "other_redacted" in queue_section
    for forbidden in (
        "UPDATE ",
        "DELETE ",
        "INSERT ",
        "receiver",
        "message",
        "SELECT *",
    ):
        assert forbidden not in queue_section
