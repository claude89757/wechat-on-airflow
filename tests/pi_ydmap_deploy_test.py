from __future__ import annotations

import copy
import importlib.util
import io
import json
import signal
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from zoneinfo import ZoneInfo

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSTALL = load("pi_ydmap_installer_test", "pi_host/dsh_ydmap/install.py")
DEPLOY = load("pi_ydmap_deployer_test", "scripts/deploy_pi_ydmap.py")
GUARD = load("pi_ydmap_dag_guard_test", "scripts/pi_ydmap_dag_guard.py")
COMMIT = "a" * 40
HASH = "b" * 64


def health():
    return {
        "ok": True,
        "service": "dsh_ydmap",
        "protocolVersion": 2,
        "deploymentCommit": COMMIT,
        "sourceSha256": HASH,
        "venues": ["dsh", "baoti"],
        "busy": False,
    }


def observation():
    return {
        "ok": True,
        "captcha": False,
        "schema_version": 2,
        "venue": "baoti",
        "days": [
            {
                "date": "2026-11-01",
                "courts": {},
                "groups": [
                    {
                        "key": key,
                        "sales_item_id": product,
                        "source_date": "2026-11-01",
                        "selected_date": "2026-11-01",
                        "court_names": ["1号场"],
                        "cell_count": 24,
                        "product_name": {
                            "outdoor": "室外网球场",
                            "indoor": "室内网球场",
                            "windrain": "风雨网球场",
                        }[key],
                        "source_host": "bawtt.ydmap.cn",
                        "source_sales_id": "104036",
                        "load_generation": 3,
                        "data_version": {"platforms": 5, "orders": 6},
                        "freshness": "both_source_arrays_replaced_after_date_selection",
                    }
                    for key, product in (
                        ("outdoor", "111317"),
                        ("indoor", "103224"),
                        ("windrain", "111319"),
                    )
                ],
            }
        ],
    }


def drain_proof():
    return {
        "schema_version": 1,
        "guard_id": "c" * 32,
        "target_commit": COMMIT,
        "drained": True,
        "active_tasks": 0,
        "active_runs": 0,
        "issued_at": int(time.time()),
        "expires_at": int(time.time()) + INSTALL.LEASE_SECONDS - INSTALL.PROOF_MARGIN_SECONDS,
        "dags": [{"dag_id": INSTALL.DAG_IDS[0], "was_paused": False, "paused": True}],
    }


@pytest.mark.parametrize(
    "field,value",
    [
        ("protocolVersion", 1),
        ("deploymentCommit", "c" * 40),
        ("sourceSha256", "d" * 64),
        ("venues", ["dsh"]),
    ],
)
def test_health_requires_all_runtime_identity_fields(field, value):
    payload = {**health(), field: value}
    with pytest.raises(INSTALL.OperationFailure, match="scraper_identity_mismatch"):
        INSTALL.verify_health(payload, COMMIT, HASH)


def test_inspection_requires_independent_date_product_and_court_evidence():
    valid = observation()
    report = INSTALL.inspect_evidence(valid, "baoti", ["2026-11-01"])
    assert report["verified"] is True
    assert len(report["days"][0]["groups"]) == 3
    mutations = []
    missing = copy.deepcopy(valid)
    missing["days"][0]["groups"].pop()
    mutations.append(missing)
    wrong_date = copy.deepcopy(valid)
    wrong_date["days"][0]["groups"][0]["source_date"] = "2026-10-31"
    mutations.append(wrong_date)
    empty_cells = copy.deepcopy(valid)
    empty_cells["days"][0]["groups"][0]["cell_count"] = 0
    mutations.append(empty_cells)
    wrong_venue = {**valid, "venue": "dsh"}
    mutations.append(wrong_venue)
    legacy = copy.deepcopy(valid)
    legacy.pop("schema_version")
    mutations.append(legacy)
    secret_name = copy.deepcopy(valid)
    secret_name["days"][0]["groups"][0]["court_names"] = ["https://private.test?token=secret"]
    mutations.append(secret_name)
    mismatched_product = copy.deepcopy(valid)
    mismatched_product["days"][0]["groups"][0]["product_name"] = "室内网球场"
    mutations.append(mismatched_product)
    swapped = copy.deepcopy(valid)
    (
        swapped["days"][0]["groups"][0]["sales_item_id"],
        swapped["days"][0]["groups"][1]["sales_item_id"],
    ) = "103224", "111317"
    mutations.append(swapped)
    for field, value in (
        ("freshness", "unverified"),
        ("load_generation", 0),
        ("data_version", {"platforms": 1, "orders": 0}),
    ):
        stale = copy.deepcopy(valid)
        stale["days"][0]["groups"][0][field] = value
        mutations.append(stale)
    for ranges in (
        [["25:00", "26:00"]],
        [["20:00", "19:00"]],
        [["24:00", "24:00"]],
        [["19:00", "20:00", "bad"]],
    ):
        invalid_slots = copy.deepcopy(valid)
        invalid_slots["days"][0]["courts"] = {"1号场": ranges}
        mutations.append(invalid_slots)
    for payload in mutations:
        with pytest.raises(INSTALL.OperationFailure):
            INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"])


def test_candidate_failure_never_replaces_or_stops_live_service(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(INSTALL, "other_service_identities", lambda: {"other": "unchanged"})
    monkeypatch.setattr(INSTALL, "verify_existing_service", lambda: object())
    monkeypatch.setattr(INSTALL, "request_json", lambda *a, **k: health())
    monkeypatch.setattr(INSTALL, "prepare_candidate", lambda *a: tmp_path)

    @contextmanager
    def candidate(*args):
        yield 18788

    monkeypatch.setattr(INSTALL, "isolated_candidate", candidate)
    monkeypatch.setattr(
        INSTALL,
        "inspect_venues",
        lambda *a: (_ for _ in ()).throw(INSTALL.OperationFailure("access_verification")),
    )
    monkeypatch.setattr(INSTALL, "activate", lambda *a: calls.append("activate"))
    monkeypatch.setattr(INSTALL, "run", lambda *a, **k: calls.append(a))
    args = SimpleNamespace(
        operation="apply",
        commit=COMMIT,
        source_sha256=HASH,
        staging=tmp_path,
        drain_proof=drain_proof(),
    )
    with pytest.raises(INSTALL.OperationFailure, match="access_verification"):
        INSTALL.operate(args)
    assert calls == []


def test_any_apply_requires_measured_protected_drain(monkeypatch, tmp_path):
    monkeypatch.setattr(INSTALL, "other_service_identities", lambda: {})
    monkeypatch.setattr(INSTALL, "verify_existing_service", lambda: object())
    monkeypatch.setattr(INSTALL, "request_json", lambda *a: {"ok": True, "service": "dsh_ydmap"})
    args = SimpleNamespace(
        operation="apply",
        commit=COMMIT,
        source_sha256=HASH,
        staging=tmp_path,
        drain_proof=None,
    )
    with pytest.raises(INSTALL.OperationFailure, match="dag_drain_proof_required"):
        INSTALL.operate(args)


@pytest.mark.parametrize(
    "field,value",
    [
        ("active_tasks", 1),
        ("active_runs", 1),
        ("target_commit", "d" * 40),
        ("expires_at", 0),
        ("dags", []),
    ],
)
def test_drain_proof_rejects_busy_expired_or_wrong_target(field, value):
    with pytest.raises(INSTALL.OperationFailure):
        INSTALL.validate_drain_proof({**drain_proof(), field: value}, COMMIT)


@pytest.mark.parametrize(
    "with_baoti,release_reason",
    [(False, "release"), (True, "release"), (True, "eof"), (True, "timeout")],
)
def test_dag_guard_restores_exact_flags_after_success_disconnect_or_timeout(
    with_baoti, release_reason
):
    flags = {GUARD.DAG_IDS[0]: False, "unrelated": False}
    if with_baoti:
        flags[GUARD.DAG_IDS[1]] = True
    original = dict(flags)
    clock = [0.0]
    counts = iter(((1, 1), (0, 0), (0, 0)))
    events = []

    class Backend:
        def pause(self):
            state = {key: flags[key] for key in GUARD.DAG_IDS if key in flags}
            for key in state:
                flags[key] = True
            return state

        def counts(self, state):
            assert all(flags[key] for key in state)
            assert flags["unrelated"] is False
            return next(counts)

        def restore(self, state):
            flags.update(state)
            return all(flags[key] == value for key, value in state.items())

    def release(timeout):
        assert events[-1]["event"] == "drained"
        assert events[-1]["proof"]["active_tasks"] == 0
        assert flags[GUARD.DAG_IDS[0]] is True
        return release_reason

    result = GUARD.run_guard(
        Backend(),
        COMMIT,
        "c" * 32,
        emit=events.append,
        release=release,
        monotonic=lambda: clock[0],
        now=lambda: 1000,
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    assert flags == original
    assert events[-1]["event"] == "restored" and events[-1]["ok"] is True
    assert result == (0 if release_reason == "release" else 1)
    issued_clock = 4
    if release_reason != "release":
        assert clock[0] >= issued_clock + GUARD.HOLD_SECONDS
    else:
        assert clock[0] < GUARD.HOLD_SECONDS


def test_drain_timeout_restores_and_never_issues_an_apply_proof():
    state = {GUARD.DAG_IDS[0]: False}
    clock = [0.0]
    events = []
    restored = []
    backend = SimpleNamespace(
        pause=lambda: state,
        counts=lambda _: (1, 1),
        restore=lambda original: restored.append(dict(original)) or True,
    )
    result = GUARD.run_guard(
        backend,
        COMMIT,
        "c" * 32,
        emit=events.append,
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        drain_timeout=5,
    )
    assert result == 1 and restored and all(value == state for value in restored)
    assert not any(event["event"] == "drained" for event in events)
    assert events[-1]["restored"] is True


def test_remote_failure_retains_verified_public_inspection_evidence():
    summary = INSTALL.inspect_evidence(observation(), "baoti", ["2026-11-01"])
    channel = SimpleNamespace(
        shutdown_write=lambda: None, recv_exit_status=lambda: 1, close=lambda: None
    )
    stdin = SimpleNamespace(channel=channel)
    stdout = io.BytesIO(
        json.dumps(
            {
                "ok": False,
                "operationComplete": True,
                "failure": "access_verification",
                "inspections": [summary],
                "secret": "private",
            }
        ).encode()
    )
    stdout.channel = channel
    client = SimpleNamespace(exec_command=lambda *a, **k: (stdin, stdout, io.BytesIO(b"private")))
    report = DEPLOY.remote(client, "fake-command")
    assert report["inspections"] == [summary]
    assert "private" not in json.dumps(report)


@pytest.mark.parametrize("phase", ["health", "live_inspect"])
def test_failed_activation_restores_only_its_original_service_override(
    monkeypatch, tmp_path, phase
):
    base = tmp_path / "managed"
    base.mkdir()
    old = base / "old"
    old.mkdir()
    (base / "current").symlink_to(old)
    override = tmp_path / "unit/managed.conf"
    override.parent.mkdir()
    original = (INSTALL.MARKER + "[Service]\nExecStart=/old\n").encode()
    override.write_bytes(original)
    candidate = base / "candidate"
    candidate.mkdir()
    commands = []
    monkeypatch.setattr(INSTALL, "BASE", base)
    monkeypatch.setattr(INSTALL, "DROPIN", override)
    monkeypatch.setattr(INSTALL, "wait_idle", lambda: None)
    monkeypatch.setattr(INSTALL, "request_json", lambda *a: health())
    monkeypatch.setattr(INSTALL, "run", lambda argv: commands.append(argv) or "")
    failed = INSTALL.OperationFailure(
        "installed_health_failed" if phase == "health" else "access_verification"
    )
    failed.venue = "baoti"
    failed.source_failure = "rate_limited"
    monkeypatch.setattr(INSTALL, "wait_health", lambda *a: health())
    monkeypatch.setattr(INSTALL, "inspect_venues", lambda *a: [])
    monkeypatch.setattr(
        INSTALL,
        "wait_health" if phase == "health" else "inspect_venues",
        lambda *a: (_ for _ in ()).throw(failed),
    )
    with pytest.raises(INSTALL.OperationFailure, match="activation_failed") as error:
        INSTALL.activate(candidate, COMMIT, HASH, drain_proof())
    assert error.value.rollback_verified is True
    assert error.value.source_failure == "rate_limited"
    assert (base / "current").resolve() == old
    assert override.read_bytes() == original
    assert all(
        command[-1] == INSTALL.UNIT or command == ["systemctl", "daemon-reload"]
        for command in commands
    )
    assert (candidate / "rollback.json").stat().st_mode & 0o777 == 0o600


def test_activation_rechecks_full_lease_after_waiting_for_idle(monkeypatch, tmp_path):
    clock = [1000]
    commands = []
    monkeypatch.setattr(INSTALL, "BASE", tmp_path)
    monkeypatch.setattr(INSTALL, "DROPIN", tmp_path / "override")
    monkeypatch.setattr(INSTALL.time, "time", lambda: clock[0])
    monkeypatch.setattr(INSTALL, "request_json", lambda *a: health())
    monkeypatch.setattr(INSTALL, "wait_idle", lambda: clock.__setitem__(0, 1800))
    monkeypatch.setattr(INSTALL, "run", lambda *a: commands.append(a))
    proof = drain_proof()
    with pytest.raises(INSTALL.OperationFailure, match="dag_drain_proof_expired"):
        INSTALL.activate(tmp_path, COMMIT, HASH, proof)
    assert commands == []


def test_guard_does_not_release_when_pi_completion_is_unknown(monkeypatch):
    acknowledgements = []
    guard = DEPLOY.AirflowGuard(COMMIT)
    monkeypatch.setattr(guard, "close", lambda *, completed: acknowledgements.append(completed))
    with pytest.raises(RuntimeError, match="airflow_pause_restore_not_verified"):
        guard.__exit__(TimeoutError, TimeoutError(), None)
    assert acknowledgements == [False]


def test_guard_waits_for_idle_without_pausing_pending_runs():
    clock = [0]
    attempts = []
    events = []
    state = {GUARD.DAG_IDS[0]: False}

    def pause():
        attempts.append(clock[0])
        if len(attempts) < 3:
            raise GUARD.DrainBusy()
        return state

    backend = SimpleNamespace(pause=pause, counts=lambda _: (0, 0), restore=lambda _: True)
    result = GUARD.run_guard(
        backend,
        COMMIT,
        "c" * 32,
        emit=events.append,
        release=lambda _: "release",
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    assert result == 0 and attempts == [0, 2, 4]
    assert events[0]["event"] == "drained"


@pytest.mark.parametrize("release_reason", ["release", "eof"])
def test_guard_restoration_survives_signals_during_retry_sleep(release_reason):
    clock = [0]
    events = []
    attempts = []
    protected = (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)

    def interrupted(signum, frame):
        raise InterruptedError("simulated_disconnect")

    previous = {signum: signal.signal(signum, interrupted) for signum in protected}

    def restore(state):
        attempts.append(dict(state))
        return len(attempts) == 2

    def sleep(seconds):
        if attempts or events:
            for signum in protected:
                signal.raise_signal(signum)
        clock[0] += seconds

    state = {GUARD.DAG_IDS[0]: False}
    backend = SimpleNamespace(pause=lambda: state, counts=lambda _: (0, 0), restore=restore)
    try:
        result = GUARD.run_guard(
            backend,
            COMMIT,
            "c" * 32,
            emit=events.append,
            release=lambda _: release_reason,
            monotonic=lambda: clock[0],
            sleep=sleep,
        )
        assert result == (0 if release_reason == "release" else 1) and attempts == [state, state]
        if release_reason == "eof":
            assert clock[0] >= GUARD.HOLD_SECONDS
        assert events[-1]["restored"] is True
        assert all(signal.getsignal(signum) is interrupted for signum in protected)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def test_http_source_failure_is_bounded_and_preserved(monkeypatch):
    payload = {
        "ok": False,
        "error": "product_name_unverified",
        "diagnostics": {
            "pageHost": "bawtt.ydmap.cn",
            "selectedDate": "2026-11-01",
            "sourceProduct": "111317",
            "productName": None,
            "productNameField": None,
            "productInCatalog": False,
            "courtNames": ["1号室外场"],
            "secret": "private-cookie",
            "sourceSalesId": "token=private",
        },
        "cookie": "private-cookie",
    }

    def fail(*args, **kwargs):
        raise HTTPError(
            "http://127.0.0.1", 503, "unused", {}, io.BytesIO(json.dumps(payload).encode())
        )

    monkeypatch.setattr(
        INSTALL.urllib.request, "build_opener", lambda *args: SimpleNamespace(open=fail)
    )
    with pytest.raises(INSTALL.OperationFailure) as caught:
        INSTALL.request_json(8788, "/inspect")
    error = caught.value
    assert error.source_failure == "product_name_unverified"
    assert error.source_diagnostic["sourceProduct"] == "111317"
    assert error.source_diagnostic["present"]["productName"] is True
    assert error.source_diagnostic["productInCatalog"] is False
    assert "private" not in json.dumps(error.source_diagnostic)
    assert INSTALL.safe_source_diagnostic(error.source_diagnostic) == error.source_diagnostic


@pytest.mark.parametrize("hour,minute,days", [(11, 59, 4), (12, 0, 5)])
def test_inspection_matches_dashah_released_horizon(monkeypatch, hour, minute, days):
    requests = []
    monkeypatch.setattr(
        INSTALL, "request_json", lambda port, path, **kwargs: requests.append(path) or {}
    )
    monkeypatch.setattr(
        INSTALL, "inspect_evidence", lambda payload, venue, dates: {"venue": venue, "dates": dates}
    )
    result = INSTALL.inspect_venues(
        18788, at=datetime(2026, 11, 1, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))
    )
    assert requests == [f"/inspect?venue=dsh&days={days}", "/inspect?venue=baoti&days=2"]
    assert len(result[0]["dates"]) == days


def test_remote_failure_does_not_forward_raw_errors_or_upstream_data():
    channel = SimpleNamespace(
        shutdown_write=lambda: None, recv_exit_status=lambda: 1, close=lambda: None
    )
    stdin = SimpleNamespace(channel=channel)
    stdout = io.BytesIO(
        json.dumps(
            {
                "ok": False,
                "operationComplete": True,
                "failure": "secret-value",
                "private": "secret-value",
                "venue": "baoti",
            }
        ).encode()
    )
    stdout.channel = channel
    client = SimpleNamespace(
        exec_command=lambda *a, **k: (stdin, stdout, io.BytesIO(b"secret-value"))
    )
    report = DEPLOY.remote(client, "fake-command")
    assert report["failure"] == "operation_failed"
    assert report["venue"] == "baoti"
    assert "secret-value" not in json.dumps(report)


def test_workflow_gates_and_release_order_cover_pi_before_airflow():
    workflow = yaml.safe_load((ROOT / ".github/workflows/production-pi-ydmap.yml").read_text())
    job = workflow["jobs"]["operate"]
    assert job["environment"] == "production"
    assert job["if"] == "github.ref == 'refs/heads/main'"
    gate = next(
        step for step in job["steps"] if step.get("name") == "Require exact main commit and CI"
    )
    assert "github_release_gate.py" in gate["run"]
    assert "merge-base --is-ancestor" in gate["run"]
    release = yaml.safe_load((ROOT / ".github/workflows/production-release.yml").read_text())
    assert "pi_ydmap" in release["jobs"]["airflow"]["needs"]
    assert "needs.pi_ydmap.result == 'success'" in release["jobs"]["airflow"]["if"]
    assert "pi_ydmap" in release["jobs"]["record"]["needs"]
