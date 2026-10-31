from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import signal
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
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


def renderer_evidence():
    source = 'function textFun() { return "已预订"; }'
    size = len(source.encode("utf-8"))
    return {
        "schema_version": 1,
        "bookability_verified": False,
        "source_cell_count": 24,
        "matched_cell_count": 24,
        "unmatched_cell_count": 0,
        "coverage_complete": True,
        "component_scan_truncated": False,
        "source_truncated": False,
        "components": [
            {
                "index": 0,
                "name": "ScheduleCell",
                "matched_cell_count": 24,
                "methods": {name: name == "textFun" for name in INSTALL.RENDERER_METHODS},
            }
        ],
        "methods": [
            {
                "component_indices": [0],
                "name": "textFun",
                "kind": "method",
                "sha256": hashlib.sha256(source.encode()).hexdigest(),
                "source": source,
                "original_bytes": size,
                "emitted_bytes": size,
                "truncated": False,
                "redacted": False,
                "reused": False,
            }
        ],
        "samples": [
            {
                "included": False,
                "court": "室外1号场",
                "start": "19:00",
                "end": "20:00",
                "known_classes": ["col-completed"],
                "expired": False,
                "order_no_book": False,
                "has_order": True,
                "has_price": True,
                "online_booking": 1,
                "online_booking_redacted": False,
            }
        ],
    }


def observation_with_source():
    value = observation()
    value["days"][0]["groups"][0]["source_evidence"] = renderer_evidence()
    return value


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


@pytest.mark.skipif(sys.platform != "linux", reason="runuser is a Linux runtime prerequisite")
def test_candidate_launcher_executes_with_its_restricted_path(monkeypatch, tmp_path):
    # Exercise the actual executable lookup with the candidate's environment;
    # a mocked Popen alone would miss a bare runuser hidden outside PATH.
    real_popen = INSTALL.subprocess.Popen
    runtime = tmp_path / "candidate-runtime"
    runtime.mkdir()
    account = SimpleNamespace(pw_name="pi-test", pw_uid=1000, pw_gid=1000, pw_dir=str(tmp_path))
    polls = iter((None, 0))
    launches = []
    cleanup = []

    def launch(command, **kwargs):
        assert Path(command[0]).is_absolute()
        assert "/usr/sbin" not in kwargs["env"]["PATH"].split(":")
        with real_popen(
            [command[0], "--version"],
            env=kwargs["env"],
            stdout=INSTALL.subprocess.PIPE,
            stderr=INSTALL.subprocess.PIPE,
        ) as probe:
            output, _ = probe.communicate(timeout=5)
            assert probe.returncode == 0 and b"runuser" in output
        launches.append(command)
        return SimpleNamespace(poll=lambda: next(polls))

    monkeypatch.setattr(INSTALL.tempfile, "mkdtemp", lambda **kwargs: str(runtime))
    monkeypatch.setattr(INSTALL.os, "chown", lambda *args: None)
    monkeypatch.setattr(INSTALL.subprocess, "Popen", launch)
    monkeypatch.setattr(INSTALL.subprocess, "run", lambda argv, **kwargs: cleanup.append(argv))
    monkeypatch.setattr(INSTALL, "request_json", lambda *args: health())
    with INSTALL.isolated_candidate(tmp_path, account, COMMIT) as port:
        assert port == 18788
    assert launches[0][:4] == [INSTALL.checked_runuser(), "-u", "pi-test", "--"]
    assert len(cleanup) == 1 and "19224" in cleanup[0][-1]
    assert not runtime.exists()


def test_missing_runuser_fails_before_candidate_directory_creation(monkeypatch, tmp_path):
    monkeypatch.setattr(INSTALL, "RUNUSER", tmp_path / "missing-runuser")
    monkeypatch.setattr(
        INSTALL.tempfile, "mkdtemp", lambda **kwargs: pytest.fail("candidate must not be created")
    )
    with pytest.raises(INSTALL.OperationFailure, match="runuser_unavailable"):
        with INSTALL.isolated_candidate(tmp_path, object(), COMMIT):
            pytest.fail("missing launcher cannot start a candidate")


def test_launch_exception_diagnostic_survives_remote_filter_without_private_data(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(INSTALL, "checked_runuser", lambda: "/usr/sbin/runuser")
    runtime = tmp_path / "candidate-runtime"
    runtime.mkdir()
    account = SimpleNamespace(pw_name="pi-test", pw_uid=1000, pw_gid=1000, pw_dir=str(tmp_path))
    monkeypatch.setattr(
        INSTALL.sys,
        "argv",
        [
            "install.py",
            "preflight",
            "--commit",
            COMMIT,
            "--source-sha256",
            HASH,
            "--staging",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(INSTALL.os, "geteuid", lambda: 0)
    monkeypatch.setattr(INSTALL.os, "chown", lambda *args: None)
    monkeypatch.setattr(INSTALL, "other_service_identities", lambda: {})
    monkeypatch.setattr(INSTALL, "verify_existing_service", lambda: account)
    monkeypatch.setattr(INSTALL, "prepare_candidate", lambda *args: tmp_path)
    monkeypatch.setattr(INSTALL.tempfile, "mkdtemp", lambda **kwargs: str(runtime))

    def failed_launch(*args, **kwargs):
        raise FileNotFoundError("private path and secret-value")

    monkeypatch.setattr(INSTALL.subprocess, "Popen", failed_launch)
    monkeypatch.setattr(
        INSTALL.subprocess, "run", lambda *args, **kwargs: pytest.fail("no process was started")
    )
    handlers = {
        signum: signal.getsignal(signum)
        for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT)
    }
    try:
        assert INSTALL.main() == 1
    finally:
        for signum, handler in handlers.items():
            signal.signal(signum, handler)
    payload = json.loads(capsys.readouterr().out)
    assert payload["errorClass"] == "FileNotFoundError"
    assert payload["failureDiagnostic"]["phase"] == "candidate_runtime"
    assert payload["failureDiagnostic"]["function"] == "isolated_candidate"
    assert type(payload["failureDiagnostic"]["line"]) is int
    assert not runtime.exists()
    assert "secret-value" not in json.dumps(payload)
    channel = SimpleNamespace(
        shutdown_write=lambda: None, recv_exit_status=lambda: 1, close=lambda: None
    )
    stdout = io.BytesIO(json.dumps(payload).encode())
    stdout.channel = channel
    client = SimpleNamespace(
        exec_command=lambda *a, **k: (
            SimpleNamespace(channel=channel),
            stdout,
            io.BytesIO(b"secret-value"),
        )
    )
    retained = DEPLOY.remote(client, "fake-command")
    assert retained["errorClass"] == payload["errorClass"]
    assert retained["failureDiagnostic"] == payload["failureDiagnostic"]
    assert retained["inspections"] == []
    assert "secret-value" not in json.dumps(retained)


@pytest.mark.parametrize("field,value", [("phase", []), ("function", {}), ("line", True)])
def test_failure_diagnostic_rejects_malformed_untrusted_fields(field, value):
    diagnostic = {"phase": "candidate_runtime", "function": "isolated_candidate", "line": 1200}
    assert INSTALL.safe_failure_diagnostic({**diagnostic, field: value}) is None
    assert INSTALL.safe_error_class("secret-value") == "Exception"
    assert INSTALL.safe_failure_diagnostic({**diagnostic, "private": "secret-value"}) == diagnostic


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
            "challengeMaskVisible": True,
            "challengeText": "private-token",
            "failurePhase": "initial_schedule",
            "requestedProduct": "111317",
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
    assert error.source_diagnostic["challengeMaskVisible"] is True
    assert "challengeText" not in error.source_diagnostic
    assert error.source_diagnostic["failurePhase"] == "initial_schedule"
    assert error.source_diagnostic["requestedProduct"] == "111317"
    assert "failurePhase" not in INSTALL.safe_source_diagnostic({"failurePhase": "private"})
    assert INSTALL.safe_source_failure("JavascriptException") == "JavascriptException"
    assert INSTALL.safe_source_failure("private-cookie-value") is None
    assert "private" not in json.dumps(error.source_diagnostic)
    assert INSTALL.safe_source_diagnostic(error.source_diagnostic) == error.source_diagnostic


@pytest.mark.parametrize("hour,minute,days", [(11, 59, 4), (12, 0, 5)])
def test_inspection_matches_dashah_released_horizon(monkeypatch, hour, minute, days):
    requests = []
    monkeypatch.setattr(
        INSTALL, "request_json", lambda port, path, **kwargs: requests.append(path) or {}
    )
    monkeypatch.setattr(
        INSTALL,
        "inspect_evidence",
        lambda payload, venue, dates, **kwargs: {"venue": venue, "dates": dates},
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


def test_source_evidence_is_opt_in_and_strips_unknown_sensitive_fields():
    payload = observation_with_source()
    optional = payload["days"][0]["groups"][0]["source_evidence"]
    optional["cookies"] = {"session": "private-value"}
    optional["components"][0]["user"] = "private-value"
    optional["methods"][0]["headers"] = "private-value"
    optional["samples"][0]["orderInfo"] = {"phone": "private-value"}
    ordinary = INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"])
    assert "source_evidence" not in json.dumps(ordinary)
    report = INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"], source_evidence=True)
    retained = report["days"][0]["groups"][0]["source_evidence"]
    assert retained == renderer_evidence()
    assert retained["bookability_verified"] is False
    assert "private-value" not in json.dumps(report)
    assert INSTALL.safe_inspections([report], source_evidence=True) == [report]
    assert "source_evidence" not in json.dumps(INSTALL.safe_inspections([report]))


def test_actual_scraper_source_sanitizer_matches_report_contract():
    server = load("pi_ydmap_source_report_contract", "tests/pi_baoti_scraper_test.py").server
    assert set(server.SOURCE_CLASSES) == INSTALL.SOURCE_CLASSES
    assert set(server.SOURCE_LITERAL_ALLOWLIST).issubset(INSTALL.SOURCE_LITERAL_ALLOWLIST)
    raw = renderer_evidence()
    raw["methods"][0]["source"] = (
        'function textFun(){ /* private comment */ return "https://private.test/token"; }'
    )
    raw["methods"][0]["original_bytes"] = len(raw["methods"][0]["source"].encode())
    raw["samples"][0]["court"] = "1号场"
    budget = {"remaining": server.SOURCE_TOTAL_BYTES, "seen": set()}
    canonical = server._source_evidence(raw, "室内", budget)
    reused = server._source_evidence(raw, "室外", budget)
    assert reused["methods"][0]["reused"] is True
    payload = observation()
    payload["days"][0]["groups"][0]["source_evidence"] = reused
    payload["days"][0]["groups"][1]["source_evidence"] = canonical
    report = INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"], source_evidence=True)
    assert report["sourceEvidenceRejected"] is False
    assert report["sourceEvidenceTruncated"] is False
    assert INSTALL.safe_inspections([report], source_evidence=True) == [report]
    encoded = INSTALL.encode_report({"ok": True, "inspections": [report]}, source_evidence=True)
    assert json.loads(encoded)["inspections"] == [report]
    retained = report["days"][0]["groups"][1]["source_evidence"]
    assert retained["methods"][0]["redacted"] is True
    assert "private" not in json.dumps(retained)


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "0" * 64),
        ("emitted_bytes", 999),
        ("original_bytes", True),
        ("truncated", "false"),
        ("redacted", 1),
        ("reused", 1),
        ("name", "readCookies"),
        ("component_indices", [16]),
    ],
)
def test_invalid_source_method_metadata_is_rejected_without_losing_identity(field, value):
    payload = observation_with_source()
    payload["days"][0]["groups"][0]["source_evidence"]["methods"][0][field] = value
    report = INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"], source_evidence=True)
    assert report["verified"] is True and report["sourceEvidenceRejected"] is True
    assert "source_evidence" not in report["days"][0]["groups"][0]


@pytest.mark.parametrize(
    "source",
    [
        'function textFun(){return "private-cookie-value";}',
        "function textFun(){/* private-cookie-value */ return 1;}",
        "function textFun(){return `private-cookie-value`;}",
        "function textFun(){return " + "1" * 4097 + ";}",
    ],
)
def test_source_hash_is_not_a_substitute_for_sanitization(source):
    payload = observation_with_source()
    method = payload["days"][0]["groups"][0]["source_evidence"]["methods"][0]
    method.update(
        source=source,
        sha256=hashlib.sha256(source.encode()).hexdigest(),
        emitted_bytes=len(source.encode()),
        original_bytes=len(source.encode()),
        redacted=True,
    )
    report = INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"], source_evidence=True)
    assert report["sourceEvidenceRejected"] is True
    assert "private-cookie-value" not in json.dumps(report)


def test_source_evidence_requires_false_bookability_and_bounded_public_samples():
    for field, value in (
        ("bookability_verified", True),
        ("matched_cell_count", True),
        ("samples", [renderer_evidence()["samples"][0]] * 3),
    ):
        evidence = renderer_evidence()
        evidence[field] = value
        assert INSTALL.safe_source_evidence(evidence, cell_count=24) is None
    evidence = renderer_evidence()
    evidence["samples"][0]["online_booking"] = {"token": "private-value"}
    assert INSTALL.safe_source_evidence(evidence, cell_count=24) is None
    evidence = renderer_evidence()
    evidence["component_scan_truncated"] = True
    assert INSTALL.safe_source_evidence(evidence, cell_count=24) is None
    evidence = renderer_evidence()
    evidence["methods"][0]["truncated"] = True
    assert INSTALL.safe_source_evidence(evidence, cell_count=24) is None


def test_forward_source_reuse_is_resolved_and_unknown_hash_is_rejected():
    payload = observation_with_source()
    groups = payload["days"][0]["groups"]
    groups[1]["source_evidence"] = copy.deepcopy(groups[0]["source_evidence"])
    method = groups[0]["source_evidence"]["methods"][0]
    method.update(source="", emitted_bytes=0, reused=True)
    valid = INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"], source_evidence=True)
    assert valid["sourceEvidenceRejected"] is False
    assert valid["days"][0]["groups"][0]["source_evidence"]["methods"][0]["reused"] is True
    method["sha256"] = "f" * 64
    invalid = INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"], source_evidence=True)
    assert invalid["sourceEvidenceRejected"] is True
    assert "source_evidence" not in invalid["days"][0]["groups"][0]


def test_optional_evidence_budget_preserves_identity_and_flags_roundtrip(monkeypatch):
    report = INSTALL.inspect_evidence(
        observation_with_source(), "baoti", ["2026-11-01"], source_evidence=True
    )
    monkeypatch.setattr(INSTALL, "MAX_SOURCE_EVIDENCE_BYTES", 1)
    encoded = INSTALL.encode_report(
        {"ok": True, "operationComplete": True, "inspections": [report]}, source_evidence=True
    )
    bounded = json.loads(encoded)
    assert bounded["ok"] is True and bounded["sourceEvidenceTruncated"] is True
    assert bounded["inspections"][0]["verified"] is True
    assert "source_evidence" not in encoded
    again = json.loads(INSTALL.encode_report(bounded, source_evidence=True))
    assert again == bounded


def test_final_report_is_valid_json_below_limit_including_utf8_bytes():
    encoded = INSTALL.encode_report(
        {"ok": True, "operationComplete": True, "padding": "中" * INSTALL.MAX_BYTES}
    )
    assert len(encoded.encode("utf-8")) + 1 < INSTALL.MAX_BYTES
    report = json.loads(encoded)
    assert report["ok"] is False and report["failure"] == "report_too_large"


@pytest.mark.parametrize("status", [0, 1])
def test_remote_source_evidence_roundtrip_for_success_and_prior_success_on_failure(status):
    summary = INSTALL.inspect_evidence(
        observation_with_source(), "baoti", ["2026-11-01"], source_evidence=True
    )
    payload = {
        "ok": status == 0,
        "operationComplete": True,
        "failure": "access_verification",
        "venue": "dsh",
        "inspections": [summary],
    }
    channel = SimpleNamespace(
        shutdown_write=lambda: None, recv_exit_status=lambda: status, close=lambda: None
    )
    stdin = SimpleNamespace(channel=channel)

    def remote_files(*args, **kwargs):
        stdout = io.BytesIO(json.dumps(payload, ensure_ascii=False).encode())
        stdout.channel = channel
        return stdin, stdout, io.BytesIO()

    client = SimpleNamespace(exec_command=remote_files)
    retained = DEPLOY.remote(client, "fake", source_evidence=True)
    assert retained["inspections"] == [summary]
    assert (
        retained["inspections"][0]["days"][0]["groups"][0]["source_evidence"][
            "bookability_verified"
        ]
        is False
    )
    assert "source_evidence" not in json.dumps(DEPLOY.remote(client, "fake"))


@pytest.mark.parametrize("operation", ["preflight", "apply", "health", "inspect"])
def test_only_preflight_requests_source_evidence(monkeypatch, tmp_path, operation):
    calls = []
    monkeypatch.setattr(INSTALL, "other_service_identities", lambda: {})
    monkeypatch.setattr(INSTALL, "verify_existing_service", lambda: object())
    monkeypatch.setattr(INSTALL, "prepare_candidate", lambda *a: tmp_path)
    monkeypatch.setattr(INSTALL, "request_json", lambda *a, **k: health())
    monkeypatch.setattr(INSTALL, "activate", lambda *a: {"applied": True})
    monkeypatch.setattr(
        INSTALL,
        "inspect_venues",
        lambda port, **kwargs: calls.append((port, kwargs.get("source_evidence", False))) or [],
    )

    @contextmanager
    def candidate(*args):
        yield 18788

    monkeypatch.setattr(INSTALL, "isolated_candidate", candidate)
    INSTALL.operate(
        SimpleNamespace(
            operation=operation,
            commit=COMMIT,
            source_sha256=HASH,
            staging=tmp_path,
            drain_proof=drain_proof(),
        )
    )
    assert (
        calls
        == (
            {
                "preflight": [(18788, True)],
                "apply": [(18788, False)],
                "health": [],
                "inspect": [(8788, False)],
            }[operation]
        )
    )


def test_preflight_query_is_explicit_for_both_venues(monkeypatch):
    paths = []
    monkeypatch.setattr(
        INSTALL, "request_json", lambda port, path, **kwargs: paths.append(path) or {}
    )
    monkeypatch.setattr(INSTALL, "inspect_evidence", lambda *args, **kwargs: {})
    INSTALL.inspect_venues(
        18788, at=datetime(2026, 11, 1, 12, tzinfo=ZoneInfo("Asia/Shanghai")), source_evidence=True
    )
    assert paths == [
        "/inspect?venue=dsh&days=5&evidence=source-v1",
        "/inspect?venue=baoti&days=2&evidence=source-v1",
    ]
    paths.clear()
    INSTALL.inspect_venues(18788, source_evidence=True, verification_once=True)
    assert "verification=" not in paths[0]
    assert paths[1].endswith("&evidence=source-v1&verification=once")


@pytest.mark.parametrize("operation", ["apply", "health", "inspect"])
def test_verification_cannot_enter_live_operations(operation):
    with pytest.raises(INSTALL.OperationFailure, match="verification_not_authorized"):
        INSTALL.operate(SimpleNamespace(operation=operation, verification_once=True))


def test_verification_audit_is_allowlisted():
    safe = INSTALL.safe_source_diagnostic(
        {
            "verificationAttempted": True,
            "verificationOutcome": "not_passed",
            "private": "cookie",
        }
    )
    assert safe["verificationAttempted"] is True
    assert safe["verificationOutcome"] == "not_passed"
    assert "cookie" not in json.dumps(safe)
    unknown = INSTALL.safe_source_diagnostic(
        {"verificationAttempted": "private", "verificationOutcome": "private"}
    )
    assert "verificationAttempted" not in unknown
    assert "verificationOutcome" not in unknown


def test_browser_environment_survives_report_filter_without_raw_capabilities():
    payload = observation()
    payload["diagnostics"] = {
        "browserVersion": "137.0.7151.119",
        "driverVersion": "137.0.7151.119",
        "driverMajorMatchesBrowser": True,
        "userAgentVersionMatchesBrowser": True,
        "profileResetBeforeScrape": True,
        "userDataDir": "private-profile",
    }
    report = INSTALL.inspect_evidence(payload, "baoti", ["2026-11-01"], source_evidence=True)
    assert INSTALL.safe_inspections([report], source_evidence=True) == [report]
    assert report["browserVersion"] == "137.0.7151.119"
    assert "private" not in json.dumps(report)
    assert "browserVersion" not in INSTALL.safe_source_diagnostic({"browserVersion": "private"})


@pytest.mark.parametrize("baoti_fails", [False, True])
def test_preflight_inspects_baoti_after_dsh_failure_without_accepting_partial_success(
    monkeypatch, baoti_fails
):
    paths = []

    def request(port, path, **kwargs):
        paths.append(path)
        if "venue=dsh" in path or baoti_fails:
            failure = INSTALL.OperationFailure("scrape_not_verified")
            failure.source_failure = (
                "RuntimeError" if "venue=baoti" in path else "schedule_not_ready"
            )
            raise failure
        return {}

    monkeypatch.setattr(INSTALL, "request_json", request)
    monkeypatch.setattr(
        INSTALL, "inspect_evidence", lambda payload, venue, dates, **kwargs: {"venue": venue}
    )
    with pytest.raises(INSTALL.OperationFailure) as caught:
        INSTALL.inspect_venues(18788, source_evidence=True)
    assert len(paths) == 2
    failure = caught.value
    assert failure.venue == ("baoti" if baoti_fails else "dsh")
    assert failure.inspections == ([] if baoti_fails else [{"venue": "baoti"}])
    expected = ["dsh", "baoti"] if baoti_fails else ["dsh"]
    assert INSTALL.safe_source_diagnostic(failure.source_diagnostic)["failedVenues"] == expected
    assert "failedVenues" not in INSTALL.safe_source_diagnostic({"failedVenues": ["private"]})


def test_apply_inspection_still_stops_after_first_failure(monkeypatch):
    request = Mock(side_effect=INSTALL.OperationFailure("scrape_not_verified"))
    monkeypatch.setattr(INSTALL, "request_json", request)
    with pytest.raises(INSTALL.OperationFailure):
        INSTALL.inspect_venues(18788)
    assert request.call_count == 1


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


def test_access_diagnostics_are_bounded_numeric_and_survive_repeated_sanitization():
    raw = {
        "accessDiagnostics": {
            "documentHidden": 1,
            "scriptReferences": 3,
            "consoleHttp403Errors": 1,
            "mimeTypeErrors": 1,
            "legacyHandles": 1,
            "semanticHandles": 0,
            "frames": 2,
            "orderHtmlResponses": 1,
            "scriptFailures": 3,
            "lastOrderStatus": 200,
            "maskRoots": True,
            "maskChildren": -1,
            "dnsFailures": 10001,
            "referenceErrors": "private",
            "url": "private",
            "cookies": "private",
        }
    }
    safe = INSTALL.safe_source_diagnostic(raw)
    assert safe["accessDiagnostics"] == {
        "documentHidden": 1,
        "scriptReferences": 3,
        "consoleHttp403Errors": 1,
        "mimeTypeErrors": 1,
        "legacyHandles": 1,
        "semanticHandles": 0,
        "frames": 2,
        "orderHtmlResponses": 1,
        "scriptFailures": 3,
        "lastOrderStatus": 200,
    }
    assert INSTALL.safe_source_diagnostic(safe) == safe
    assert "private" not in json.dumps(safe)


@pytest.mark.parametrize("operation", ["apply", "health", "inspect"])
def test_product_order_probe_is_rejected_before_live_operations(operation):
    with pytest.raises(INSTALL.OperationFailure, match="verification_not_authorized"):
        INSTALL.operate(SimpleNamespace(operation=operation, first_product="windrain"))


def test_product_order_probe_cannot_mark_candidate_verified_or_activate(monkeypatch, tmp_path):
    monkeypatch.setattr(INSTALL, "other_service_identities", lambda: {})
    monkeypatch.setattr(INSTALL, "verify_existing_service", lambda: object())
    monkeypatch.setattr(INSTALL, "prepare_candidate", lambda *a: tmp_path)
    monkeypatch.setattr(INSTALL, "request_json", lambda *a, **k: health())
    monkeypatch.setattr(INSTALL, "inspect_venues", lambda *a, **k: [])
    calls = []

    @contextmanager
    def candidate(*args, **kwargs):
        calls.append(kwargs)
        yield 18788

    monkeypatch.setattr(INSTALL, "isolated_candidate", candidate)
    monkeypatch.setattr(INSTALL, "activate", lambda *a: pytest.fail("must not activate"))
    with pytest.raises(INSTALL.OperationFailure, match="diagnostic_only"):
        INSTALL.operate(
            SimpleNamespace(
                operation="preflight",
                first_product="windrain",
                commit=COMMIT,
                source_sha256=HASH,
                staging=tmp_path,
            )
        )
    assert calls == [{"first_product": "windrain"}]


def test_per_venue_failure_diagnostics_are_bounded_and_idempotent():
    nested = {
        "accessDiagnostics": {"typeErrors": 1, "private": "never-export"},
        "failedVenueDiagnostics": {"baoti": {"sourceDiagnostic": {"private": "never-export"}}},
    }
    safe = INSTALL.safe_source_diagnostic(
        {
            "failedVenueDiagnostics": {
                "dsh": {"sourceFailure": "schedule_not_ready", "sourceDiagnostic": nested},
                "baoti": {"sourceFailure": "captcha", "sourceDiagnostic": nested},
                "private": {"sourceFailure": "never-export"},
            }
        }
    )
    assert set(safe["failedVenueDiagnostics"]) == {"dsh", "baoti"}
    for item in safe["failedVenueDiagnostics"].values():
        assert item["sourceDiagnostic"]["accessDiagnostics"] == {"typeErrors": 1}
        assert "failedVenueDiagnostics" not in item["sourceDiagnostic"]
    assert "never-export" not in json.dumps(safe)
    assert INSTALL.safe_source_diagnostic(safe) == safe
