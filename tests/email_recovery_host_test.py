from __future__ import annotations

import ast
import importlib.util
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location(
    "email_recovery_host_test", ROOT / "scripts/email_recovery_host.py"
)
assert SPEC and SPEC.loader
HOST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HOST)

SHA = "a" * 40
BEFORE = "2026-11-01T02:00:00+00:00"
GENERATED = "2026-11-01T02:01:00+00:00"
ENABLED = "2026-11-01T02:02:00+00:00"
IDENTITIES = {
    key: {
        "id": str(index) * 64,
        "image": "sha256:same",
        "status": "running" if key == "api" else "exited",
    }
    for index, key in enumerate(("api", "mail", "wechat"), 1)
}


def snapshot(active=False, token=BEFORE, heartbeat=None):
    return {
        "ok": True,
        "generatedAt": GENERATED,
        "state": {
            "deploymentCommit": SHA,
            "deliveryEnabled": active,
            "wechatEnabled": False,
            "updatedAt": token,
        },
        "schemaReady": True,
        "emailConfiguration": True,
        "migrationComplete": True,
        "everActivated": True,
        "freshVenueCount": 25,
        "heartbeat": heartbeat,
    }


def install_baseline(monkeypatch, initial=None):
    events = []
    initial = initial or snapshot()
    monkeypatch.setattr(HOST, "container_identity", lambda expected, **kw: deepcopy(IDENTITIES))
    monkeypatch.setattr(HOST, "endpoint_checks", lambda expected: None)
    monkeypatch.setattr(HOST, "run", lambda command, **kwargs: events.append(tuple(command)) or "")

    def probe(options, identities, operation="snapshot", token="", since="", use_mail=False):
        events.append((operation, token))
        if operation == "enable":
            return {"ok": True, "updatedAt": ENABLED}
        if operation == "pause":
            return {"ok": True, "updatedAt": "2026-11-01T02:04:00+00:00"}
        return deepcopy(initial)

    monkeypatch.setattr(HOST, "probe", probe)
    return events


def test_preflight_never_starts_containers_or_mutates_gate(monkeypatch):
    events = install_baseline(monkeypatch)
    result = HOST.recover({"runtimeCommit": SHA, "operation": "preflight"})
    assert result["ok"] is True
    assert events == [("snapshot", "")]


@pytest.mark.parametrize(
    "field", ["schemaReady", "migrationComplete", "everActivated", "emailConfiguration"]
)
def test_missing_prerequisite_cannot_start_worker(monkeypatch, field):
    initial = snapshot()
    initial[field] = False
    events = install_baseline(monkeypatch, initial)
    with pytest.raises(HOST.RecoveryError):
        HOST.recover({"runtimeCommit": SHA, "operation": "resume"})
    assert events == [("snapshot", "")]


def test_resume_opens_gate_only_after_new_shadow_heartbeat_and_preserves_other_services(
    monkeypatch,
):
    events = install_baseline(monkeypatch)

    def wait(options, identities, token, since, active):
        events.append(("heartbeat", active, token, since))
        return snapshot(active=active, token=token)

    monkeypatch.setattr(HOST, "wait_for_worker", wait)
    result = HOST.recover({"runtimeCommit": SHA, "operation": "resume"})
    assert result["ok"] is True
    assert events == [
        ("snapshot", ""),
        ("docker", "start", IDENTITIES["mail"]["id"]),
        ("heartbeat", False, BEFORE, GENERATED),
        ("enable", BEFORE),
        ("heartbeat", True, ENABLED, ENABLED),
    ]
    assert result["runtimeChanged"] is False
    assert result["wechatChanged"] is False
    assert result["fullReleaseAccepted"] is False


def test_worker_start_failure_stops_only_original_container_while_gate_remains_closed(monkeypatch):
    events = install_baseline(monkeypatch)

    def failed_heartbeat(*args):
        raise HOST.RecoveryError("startup heartbeat failed")

    monkeypatch.setattr(HOST, "wait_for_worker", failed_heartbeat)
    result = HOST.recover({"runtimeCommit": SHA, "operation": "resume"})
    assert result["ok"] is False
    assert result["rollback"]["ok"] is True
    assert ("enable", BEFORE) not in events
    assert events[-1] == ("docker", "stop", "--time", "40", IDENTITIES["mail"]["id"])


def test_rollback_refuses_to_pause_a_later_operator_state(monkeypatch):
    later = snapshot(active=True, token="2026-11-01T03:00:00+00:00")
    events = install_baseline(monkeypatch, later)
    result = HOST.rollback({"runtimeCommit": SHA}, IDENTITIES, snapshot(), ENABLED)
    assert result == {"ok": False, "reason": "state_changed_no_rollback"}
    assert events == [("snapshot", "")]


def test_lost_activation_result_is_not_replayed_or_rolled_back_blindly(monkeypatch):
    events = install_baseline(monkeypatch, snapshot(active=True, token=ENABLED))
    result = HOST.rollback({"runtimeCommit": SHA}, IDENTITIES, snapshot(), None)
    assert result["reason"] == "activation_result_uncertain_do_not_replay"
    assert events == [("snapshot", "")]


def test_rollback_fences_its_own_activation_before_stopping(monkeypatch):
    events = install_baseline(monkeypatch, snapshot(active=True, token=ENABLED))
    result = HOST.rollback({"runtimeCommit": SHA}, IDENTITIES, snapshot(), ENABLED)
    assert result["ok"] is True
    assert events == [
        ("snapshot", ""),
        ("pause", ENABLED),
        ("docker", "stop", "--time", "40", IDENTITIES["mail"]["id"]),
    ]


def test_rollback_can_use_existing_mail_container_when_api_stopped(monkeypatch):
    events = install_baseline(monkeypatch, snapshot(active=True, token=ENABLED))

    def identity(expected, allow_api_stopped=False):
        assert allow_api_stopped is True
        current = deepcopy(IDENTITIES)
        current["api"]["status"] = "exited"
        current["mail"]["status"] = "running"
        return current

    def fallback_probe(
        options, identities, operation="snapshot", token="", since="", use_mail=False
    ):
        if not use_mail:
            raise HOST.RecoveryError("API stopped")
        events.append((operation, token, "mail-container"))
        return snapshot(active=True, token=ENABLED) if operation == "snapshot" else {"ok": True}

    monkeypatch.setattr(HOST, "container_identity", identity)
    monkeypatch.setattr(HOST, "probe", fallback_probe)
    result = HOST.rollback({"runtimeCommit": SHA}, IDENTITIES, snapshot(), ENABLED)
    assert result["ok"] is True
    assert ("pause", ENABLED, "mail-container") in events


def test_schema_guard_precedes_health_endpoints_that_can_initialize_schema(monkeypatch):
    initial = snapshot()
    initial["schemaReady"] = False
    install_baseline(monkeypatch, initial)
    monkeypatch.setattr(
        HOST, "endpoint_checks", lambda expected: pytest.fail("health before schema guard")
    )
    with pytest.raises(HOST.RecoveryError):
        HOST.recover({"runtimeCommit": SHA, "operation": "preflight"})


def test_active_resume_is_observation_only(monkeypatch):
    initial = snapshot(active=True)
    initial["heartbeat"] = {
        "deploymentCommit": SHA,
        "healthy": True,
        "updatedAt": "2026-11-01T02:00:55+00:00",
        "mode": "active",
        "owner": True,
    }
    events = install_baseline(monkeypatch, initial)
    current = deepcopy(IDENTITIES)
    current["mail"]["status"] = "running"
    monkeypatch.setattr(HOST, "container_identity", lambda expected: current)
    result = HOST.recover({"runtimeCommit": SHA, "operation": "resume"})
    assert result["ok"] is True and result["alreadyActive"] is True
    assert events == [("snapshot", "")]


@pytest.mark.parametrize(
    "mode,owner,at",
    [
        ("shadow", False, "2026-11-01T02:00:55+00:00"),
        ("active", True, "2026-11-01T01:58:00+00:00"),
        ("active", True, "2026-11-01T02:00:00+00:00"),
    ],
)
def test_shadow_or_pre_recovery_heartbeat_is_not_active_recovery(mode, owner, at):
    current = snapshot(
        True,
        heartbeat={
            "deploymentCommit": SHA,
            "healthy": True,
            "updatedAt": at,
            "mode": mode,
            "owner": owner,
        },
    )
    assert HOST.fresh_heartbeat(current, SHA, BEFORE, True) is False


def test_host_payload_remains_compatible_with_existing_python36():
    source = (ROOT / "scripts/email_recovery_host.py").read_text()
    ast.parse(source, feature_version=(3, 6))
    assert "capture_output=True" not in source
    assert "from __future__ import annotations" not in source


def test_inspection_never_returns_container_credentials(monkeypatch):
    raw = [
        {
            "Id": "1" * 64,
            "Image": "sha256:only-image",
            "State": {"Status": "exited"},
            "Config": {
                "Env": ["SECRET_DO_NOT_EXPOSE=never-print", "DEPLOYMENT_COMMIT=" + SHA],
                "Labels": {"com.docker.compose.service": HOST.MAIL},
                "Cmd": ["python", "-m", "wechat_airflow.host_core.worker"],
            },
        }
    ]
    monkeypatch.setattr(HOST, "run", lambda cmd, **kw: "1" * 64 if "ps" in cmd else json.dumps(raw))
    rendered = json.dumps(HOST.container_info(HOST.MAIL))
    assert "never-print" not in rendered and "SECRET_DO_NOT_EXPOSE" not in rendered
