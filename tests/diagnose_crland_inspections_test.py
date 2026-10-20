from __future__ import annotations

import builtins
import copy
import json
import logging
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import Column, DateTime, Integer, String, create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, declarative_base, scoped_session, sessionmaker

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import diagnose_crland_inspections as probe  # noqa: E402

COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
CANARY = "PRIVATE_SYNTHETIC_CANARY"
PRIVATE_VALUES = (
    CANARY,
    "Wechat synthetic.header.signature",
    "synthetic-recipient@example.invalid",
    "synthetic-openid",
    "19900000000",
)
NOW = datetime(2026, 10, 20, 4, 6, tzinfo=UTC)
Base = declarative_base()


class DagRun(Base):
    __tablename__ = "dag_run"
    id = Column(Integer, primary_key=True)
    dag_id = Column(String)
    run_id = Column(String)
    run_type = Column(String)
    state = Column(String)
    logical_date = Column(DateTime)
    data_interval_start = Column(DateTime)
    data_interval_end = Column(DateTime)
    start_date = Column(DateTime)
    end_date = Column(DateTime)


class TaskInstance(Base):
    __tablename__ = "task_instance"
    id = Column(Integer, primary_key=True)
    dag_id = Column(String)
    run_id = Column(String)
    task_id = Column(String)
    map_index = Column(Integer)
    state = Column(String)
    try_number = Column(Integer)
    start_date = Column(DateTime)
    end_date = Column(DateTime)


@pytest.fixture
def metadata(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'metadata.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        for venue_id, (dag_id, task_count) in probe.DAGS.items():
            interval = 2 if venue_id == "szw" else 3
            for index in range(4):
                scheduled = NOW - timedelta(minutes=interval * index)
                failed = venue_id == "szw" and index == 0
                run_id = f"scheduled__{scheduled.isoformat()}__{CANARY}"
                session.add(
                    DagRun(
                        dag_id=dag_id,
                        run_id=run_id,
                        run_type="scheduled",
                        state="failed" if failed else "success",
                        logical_date=scheduled,
                        data_interval_start=scheduled,
                        data_interval_end=scheduled + timedelta(minutes=interval),
                        start_date=scheduled + timedelta(seconds=1),
                        end_date=scheduled + timedelta(seconds=25),
                    )
                )
                for offset in range(task_count):
                    task_failed = failed and offset == 0
                    session.add(
                        TaskInstance(
                            dag_id=dag_id,
                            run_id=run_id,
                            task_id=f"check_and_notify_day_{offset}",
                            map_index=-1,
                            state="failed" if task_failed else "success",
                            try_number=5 if task_failed else 1,
                            start_date=scheduled + timedelta(seconds=2),
                            end_date=scheduled + timedelta(seconds=23),
                        )
                    )
            for run_type, state in (
                ("manual", "success"),
                ("backfill", "success"),
                ("scheduled", "running"),
            ):
                session.add(
                    DagRun(
                        dag_id=dag_id,
                        run_id=f"{run_type}__{state}",
                        run_type=run_type,
                        state=state,
                        logical_date=NOW + timedelta(days=1),
                    )
                )
        session.add(
            DagRun(dag_id="unrelated", run_type="scheduled", state="success", logical_date=NOW)
        )
        session.commit()
        yield session
    engine.dispose()


class SyntheticReader:
    def __init__(self):
        self.calls = []

    def read_log_chunks(self, task, try_number, metadata):
        self.calls.append((task.dag_id, task.task_id, try_number, metadata.copy()))
        interval = 2 if task.dag_id == probe.DAGS["szw"][0] else 3
        events = [
            " ".join(PRIVATE_VALUES),
            f"CRLand authorization: mode=rotation slot=2/3 round_minute_utc=2026-10-20T04:06+00:00 interval_minutes={interval}",
            "response status_code: 200",
            "api error for 不使用代理: api error code=200"
            if task.state == "failed"
            else "api success",
        ]
        return (SimpleNamespace(event=value) for value in events), {"end_of_log": True}


def report_for(dags):
    report = probe.base_report(COMMIT)
    report.update(deployed_commit=COMMIT, runtime_commit=COMMIT, dags=dags)
    return report


@pytest.fixture
def complete_report(metadata):
    return report_for(probe.collect_dags(metadata, DagRun, TaskInstance, SyntheticReader()))


def test_only_last_three_completed_scheduled_runs_and_fixed_tasks_are_read(metadata):
    statements = []
    event.listen(
        metadata.bind, "before_cursor_execute", lambda _c, _s, sql, *_args: statements.append(sql)
    )
    reader = SyntheticReader()
    report = probe.sanitize_report(
        report_for(probe.collect_dags(metadata, DagRun, TaskInstance, reader)), COMMIT
    )
    assert report["ok"] is True
    assert report["evidence_complete"] is True
    assert report["all_recent_runs_successful"] is False
    assert all(sql.lstrip().upper().startswith("SELECT") for sql in statements)
    assert len(reader.calls) == 19  # 18 fixed day tasks, plus one preceding failed attempt.
    assert [call[2] for call in reader.calls[:2]] == [4, 5]
    assert all(call[2] == 1 for call in reader.calls[2:])
    assert all(call[3] == {"end_of_log": False} for call in reader.calls)
    for dag in report["dags"]:
        interval = 2 if dag["venue_id"] == "szw" else 3
        assert [row["logical_date"] for row in dag["runs"]] == [
            (NOW - timedelta(minutes=interval * index)).isoformat() for index in range(3)
        ]
        assert all(row["run_type"] == "scheduled" for row in dag["runs"])
        assert all(
            [task["task_id"] for task in row["tasks"]]
            == ["check_and_notify_day_0", "check_and_notify_day_1", "check_and_notify_day_2"]
            for row in dag["runs"]
        )
    assert not any(private in json.dumps(report) for private in PRIVATE_VALUES)
    assert "run_id" not in json.dumps(report)


def test_historical_szw_day_3_is_not_read_but_failed_run_state_is_preserved(metadata):
    dag_id = probe.DAGS["szw"][0]
    legacy_run = (
        metadata.query(DagRun).filter(DagRun.dag_id == dag_id, DagRun.logical_date == NOW).one()
    )
    metadata.query(TaskInstance).filter(
        TaskInstance.dag_id == dag_id, TaskInstance.run_id == legacy_run.run_id
    ).update({TaskInstance.state: "success", TaskInstance.try_number: 1})
    metadata.add(
        TaskInstance(
            dag_id=dag_id,
            run_id=legacy_run.run_id,
            task_id="check_and_notify_day_3",
            map_index=-1,
            state="failed",
            try_number=7,
            start_date=NOW + timedelta(seconds=2),
            end_date=NOW + timedelta(seconds=23),
        )
    )
    metadata.commit()
    reader = SyntheticReader()
    report = probe.sanitize_report(
        report_for(probe.collect_dags(metadata, DagRun, TaskInstance, reader)), COMMIT
    )
    assert report["ok"] is True
    assert report["missing_evidence"] == []
    assert report["all_recent_runs_successful"] is False
    szw = next(dag for dag in report["dags"] if dag["venue_id"] == "szw")
    assert szw["runs"][0]["state"] == "failed"
    assert all(task["state"] == "success" for task in szw["runs"][0]["tasks"])
    assert [task["task_id"] for task in szw["runs"][0]["tasks"]] == [
        "check_and_notify_day_0",
        "check_and_notify_day_1",
        "check_and_notify_day_2",
    ]
    assert len(reader.calls) == 18
    assert all(call[1] != "check_and_notify_day_3" for call in reader.calls)


def test_scheduled_runs_excludes_null_dates_even_with_fewer_than_three_runs(metadata):
    dag_id = probe.DAGS["szw"][0]
    metadata.query(DagRun).filter(DagRun.dag_id == dag_id).delete()
    for run_type, state, logical_date in (
        ("scheduled", "success", None),
        ("scheduled", "failed", None),
        ("manual", "success", NOW + timedelta(days=1)),
        ("scheduled", "running", NOW + timedelta(minutes=1)),
        ("scheduled", "failed", NOW - timedelta(minutes=2)),
        ("scheduled", "success", NOW),
    ):
        metadata.add(
            DagRun(dag_id=dag_id, run_type=run_type, state=state, logical_date=logical_date)
        )
    metadata.commit()
    statements = []
    event.listen(
        metadata.bind, "before_cursor_execute", lambda _c, _s, sql, *_args: statements.append(sql)
    )
    rows = probe.scheduled_runs(metadata, DagRun, dag_id)
    assert [probe.safe_timestamp(row.logical_date) for row in rows] == [
        NOW.isoformat(),
        (NOW - timedelta(minutes=2)).isoformat(),
    ]
    assert [row.state for row in rows] == ["success", "failed"]
    assert len(statements) == 1
    assert "dag_run.logical_date IS NOT NULL" in statements[0]
    assert "NULLS LAST" not in statements[0]


@pytest.mark.parametrize("stage", ["query_runs", "query_tasks"])
def test_metadata_failures_report_only_safe_stage_type_and_driver_classification(metadata, stage):
    driver = SimpleNamespace(
        pgcode="57014",
        diag=SimpleNamespace(message_primary="canceling statement due to statement timeout"),
    )
    failure = OperationalError(f"SELECT {CANARY}", {"authorization": CANARY}, driver)

    class FailingSession:
        failed = False

        def query(self, model):
            if not self.failed and model is (DagRun if stage == "query_runs" else TaskInstance):
                self.failed = True
                raise failure
            return metadata.query(model)

    dags = probe.collect_dags(FailingSession(), DagRun, TaskInstance, SyntheticReader())
    report = probe.sanitize_report(report_for(dags), COMMIT)
    assert report["ok"] is False
    assert report["dags"][0]["metadata_error"] == {
        "stage": stage,
        "exception_type": "OperationalError",
        "sqlstate": "57014",
        "metadata_error_kind": "statement_timeout",
    }
    assert report["dags"][1]["metadata_error"] is None
    assert len(report["dags"][1]["runs"]) == 3
    assert "metadata_read_failed" in report["missing_evidence"]
    assert not any(private in json.dumps(report) for private in PRIVATE_VALUES)


@pytest.mark.parametrize(
    "sqlstate,message,expected",
    [
        ("57014", "canceling statement due to statement timeout", "statement_timeout"),
        ("57014", "canceling statement due to user request", "query_canceled"),
        ("57014", "canceling statement due to statement timeout " + CANARY, "query_canceled"),
        ("57014", CANARY, "query_canceled"),
        ("25006", "canceling statement due to statement timeout", "unknown"),
        (CANARY, CANARY, "unknown"),
    ],
)
def test_metadata_timeout_needs_exact_driver_code_and_message_template(sqlstate, message, expected):
    error = OperationalError(
        CANARY,
        {"token": CANARY},
        SimpleNamespace(sqlstate=sqlstate, diag=SimpleNamespace(message_primary=message)),
    )
    result = probe.classify_metadata_error(error, "query_runs")
    assert result["metadata_error_kind"] == expected
    assert result["sqlstate"] == (sqlstate if sqlstate in probe.METADATA_SQLSTATES else None)
    assert CANARY not in json.dumps(result)


@pytest.mark.parametrize("stage", ["query_runs", CANARY, [CANARY]])
def test_metadata_error_remote_fields_use_closed_allowlists_and_cannot_mark_complete(
    complete_report, stage
):
    complete_report["dags"][0]["metadata_error"] = {
        "stage": stage,
        "exception_type": CANARY,
        "sqlstate": "ABCDE",  # Shape alone does not authorize an arbitrary five-character value.
        "metadata_error_kind": CANARY,
        "message": CANARY,
        "params": PRIVATE_VALUES,
    }
    result = probe.sanitize_report(complete_report, COMMIT)
    assert result["ok"] is False
    assert "metadata_read_failed" in result["missing_evidence"]
    error = result["dags"][0]["metadata_error"]
    if stage == "query_runs":
        assert error == {
            "stage": "query_runs",
            "exception_type": "OtherError",
            "sqlstate": None,
            "metadata_error_kind": "unknown",
        }
    else:
        assert error is None
    assert not any(private in json.dumps(result) for private in PRIVATE_VALUES)


@pytest.mark.parametrize("interval", [None, 1, 2, 3])
def test_strict_templates_cover_old_and_new_rotation_api_200_and_idle(interval):
    suffix = "" if interval is None else f" interval_minutes={interval}"
    attempt = probe.empty_attempt(1)
    messages = [
        f"CRLand authorization: mode=rotation slot=3/3 round_minute_utc=2026-10-20T04:06+00:00{suffix}",
        "CRLand authorization: mode=legacy-single",
        "api success",
        "api success",
        "invalid json response",
        "response status_code: 429",
        "failed for 不使用代理: http status code=503",
        "api error for 不使用代理: api error code=200",
        "Error checking date 2026-10-20: all attempts failed: api error code=401",
        "failed for 不使用代理: request failed (ReadTimeout)",
        "Day 0: 每天0点-8点不巡检",
        "Day 3: 仅在北京时间08:00–21:00巡检，本轮不查询场地",
    ]
    for message in messages:
        probe.extract_log_signal(message, attempt)
    assert attempt["rotation_selections"] == [
        {"slot": 3, "round_minute_utc": "2026-10-20T04:06+00:00", "interval_minutes": interval}
    ]
    assert attempt["api_success_count"] == 2
    assert attempt["inspection_skipped_count"] == 2
    assert attempt["legacy_single_count"] == 1
    assert attempt["invalid_json_count"] == 1
    assert attempt["http_status_codes"] == [429, 503]
    assert attempt["api_error_codes"] == [200, 401]
    assert attempt["exception_types"] == ["ReadTimeout"]


def test_log_content_cannot_smuggle_arbitrary_values_or_extended_templates():
    attempt = probe.empty_attempt(1)
    messages = [
        *PRIVATE_VALUES,
        f"api success {CANARY}",
        f"response status_code: 200 {CANARY}",
        f"failed for 不使用代理: request failed ({CANARY})",
        f"api error for {CANARY}: api error code=401",
        f"Error checking date 2026-10-20: all attempts failed: {CANARY}",
        "api error for 不使用代理: api error code=19900000000",
        "CRLand authorization: mode=rotation slot=3/3 round_minute_utc=2026-99-99T04:06+00:00 interval_minutes=2",
        "api success\n" + CANARY,
        "x" * (probe.MAX_RECORD_LENGTH + 1),
        {"event": "api success"},
    ]
    for message in messages:
        probe.extract_log_signal(message, attempt)
    assert attempt == probe.empty_attempt(1)


def test_log_collection_has_a_hard_record_limit_and_marks_truncation():
    consumed = []

    def stream():
        for index in range(100_000):
            consumed.append(index)
            yield SimpleNamespace(event="api success")

    reader = SimpleNamespace(read_log_chunks=lambda *_args: (stream(), {"end_of_log": True}))
    result = probe.collect_attempt(reader, object(), 1)
    assert len(consumed) == probe.MAX_LOG_RECORDS + 1
    assert result["log_records_examined"] == probe.MAX_LOG_RECORDS
    assert result["api_success_count"] == probe.MAX_LOG_RECORDS
    assert result["missing_evidence"] == ["log_read_truncated"]


@pytest.mark.parametrize(
    "error", [TimeoutError(CANARY), RuntimeError(CANARY), type(CANARY, (Exception,), {})(CANARY)]
)
def test_reader_exceptions_only_expose_allowlisted_type(error):
    reader = Mock()
    reader.read_log_chunks.side_effect = error
    result = probe.collect_attempt(reader, object(), 1)
    assert CANARY not in json.dumps(result)
    assert result["exception_types"] == [probe.safe_error_type(error)]
    assert {"no_log_records", "log_read_incomplete"}.issubset(result["missing_evidence"])
    assert ("log_read_timeout" if isinstance(error, TimeoutError) else "log_read_failed") in result[
        "missing_evidence"
    ]


def test_deadline_cannot_be_swallowed_by_sdk_exception_handler():
    def read(*_args):
        try:
            probe.raise_log_timeout(0, None)
        except Exception:
            return [SimpleNamespace(event="api success")], {"end_of_log": True}

    result = probe.collect_attempt(SimpleNamespace(read_log_chunks=read), object(), 1)
    assert result["api_success_count"] == 0
    assert result["end_of_log"] is False
    assert result["exception_types"] == ["TimeoutError"]
    assert "log_read_timeout" in result["missing_evidence"]


@pytest.mark.parametrize("kind", ["empty", "incomplete", "unrecognized", "failure_without_error"])
def test_sanitizer_recalculates_missing_evidence_in_falsely_complete_payload(complete_report, kind):
    report = copy.deepcopy(complete_report)
    task = report["dags"][0]["runs"][0]["tasks"][0]
    for attempt in task["attempts"]:
        attempt["missing_evidence"] = []
        if kind == "empty":
            attempt["log_records_examined"] = 0
        elif kind == "incomplete":
            attempt["end_of_log"] = False
        elif kind == "unrecognized":
            attempt.update(probe.empty_attempt(attempt["try_number"]))
            attempt.update(log_records_examined=7, end_of_log=True)
        else:
            attempt["api_error_codes"] = []
    report.update(ok=True, evidence_complete=True, missing_evidence=[])
    result = probe.sanitize_report(report, COMMIT)
    assert result["commit_matches"] is True
    assert result["ok"] is result["evidence_complete"] is False
    expected = {
        "empty": "no_log_records",
        "incomplete": "log_read_incomplete",
        "unrecognized": "no_allowlisted_signals",
        "failure_without_error": "failure_signature_missing",
    }
    assert expected[kind] in result["missing_evidence"]


@pytest.mark.parametrize(
    "field,value,missing",
    [
        ("runtime_commit", None, "runtime_commit_missing"),
        ("runtime_commit", OTHER_COMMIT, "commit_mismatch"),
        ("deployed_commit", None, "git_commit_missing"),
        ("deployed_commit", OTHER_COMMIT, "commit_mismatch"),
    ],
)
def test_both_git_and_runtime_identity_required_but_safe_task_evidence_remains(
    complete_report, field, value, missing
):
    complete_report[field] = value
    result = probe.sanitize_report(complete_report, COMMIT)
    assert result["ok"] is False
    assert result["commit_matches"] is False
    assert missing in result["missing_evidence"]
    assert len(result["dags"][0]["runs"]) == 3
    assert result["dags"][0]["runs"][0]["tasks"][0]["attempts"][0]["api_error_codes"] == [200]


def test_remote_json_is_rebuilt_from_closed_allowlists(complete_report):
    complete_report["raw_logs"] = list(PRIVATE_VALUES)
    complete_report["expected_commit"] = CANARY
    complete_report["missing_evidence"] = [CANARY]
    run = complete_report["dags"][0]["runs"][0]
    run["run_id"] = CANARY
    run["logical_date"] = CANARY
    run["tasks"].append({"task_id": CANARY, "state": CANARY})
    task = run["tasks"][0]
    task["recipient"] = PRIVATE_VALUES[2]
    task["state"] = CANARY
    attempt = task["attempts"][1]
    attempt["exception_types"] = [CANARY, "ValueError"]
    attempt["api_error_codes"] = [True, -1, "401", 200, 19900000000]
    attempt["rotation_selections"][0]["account"] = PRIVATE_VALUES[3]
    result = probe.sanitize_report(complete_report, COMMIT)
    rendered = json.dumps(result)
    assert not any(private in rendered for private in PRIVATE_VALUES)
    assert result["expected_commit"] == COMMIT
    assert result["ok"] is False
    assert result["dags"][0]["runs"][0]["logical_date"] is None
    assert len(result["dags"][0]["runs"][0]["tasks"]) == 3


@pytest.mark.parametrize("missing_current_task", [False, True])
def test_remote_historical_day_3_is_ignored_and_cannot_replace_day_2(
    complete_report, missing_current_task
):
    run = complete_report["dags"][0]["runs"][0]
    historical_task = copy.deepcopy(run["tasks"][0])
    historical_task.update(task_id="check_and_notify_day_3", raw_logs=list(PRIVATE_VALUES))
    historical_task["attempts"][0]["raw_message"] = CANARY
    run["tasks"].append(historical_task)
    if missing_current_task:
        run["tasks"] = [
            task for task in run["tasks"] if task["task_id"] != "check_and_notify_day_2"
        ]
    report = probe.sanitize_report(complete_report, COMMIT)
    tasks = report["dags"][0]["runs"][0]["tasks"]
    assert [task["task_id"] for task in tasks] == [
        "check_and_notify_day_0",
        "check_and_notify_day_1",
        "check_and_notify_day_2",
    ]
    assert report["dags"][0]["runs"][0]["state"] == "failed"
    assert report["all_recent_runs_successful"] is False
    assert report["ok"] is (not missing_current_task)
    assert ("task_instance_missing" in report["missing_evidence"]) is missing_current_task
    if missing_current_task:
        assert tasks[2]["state"] is None
        assert tasks[2]["attempts"] == []
    rendered = json.dumps(report)
    assert "check_and_notify_day_3" not in rendered
    assert not any(private in rendered for private in PRIVATE_VALUES)


def test_missing_reader_and_total_time_budget_return_explicit_missing_evidence(
    metadata, monkeypatch
):
    missing = probe.sanitize_report(
        report_for(probe.collect_dags(metadata, DagRun, TaskInstance, None)), COMMIT
    )
    assert "log_reader_unavailable" in missing["missing_evidence"]
    reader = SyntheticReader()
    monkeypatch.setattr(probe, "COLLECTION_SECONDS", 0)
    timed = probe.sanitize_report(
        report_for(probe.collect_dags(metadata, DagRun, TaskInstance, reader)), COMMIT
    )
    assert "collection_time_limit" in timed["missing_evidence"]
    assert not reader.calls
    assert len(timed["dags"][1]["runs"]) == 3


def test_quiet_runtime_suppresses_standard_and_existing_logger_streams(capfd):
    logger = logging.getLogger("synthetic.crland.diagnosis")
    handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(handler)
    previous_disable = logging.root.manager.disable
    try:
        with probe.quiet_runtime():
            print(CANARY)
            print(CANARY, file=sys.stderr)
            os.write(1, CANARY.encode())
            os.write(2, CANARY.encode())
            logger.critical(CANARY)
        assert logging.root.manager.disable == previous_disable
        print("restored")
        captured = capfd.readouterr()
        assert captured.out == "restored\n"
        assert captured.err == ""
    finally:
        logger.removeHandler(handler)
        handler.close()


def test_embedded_airflow_33_reader_execution_is_quiet_and_transaction_read_only(
    metadata, monkeypatch, capfd
):
    code = compile(probe.remote_python(), "<remote-crland-diagnostic>", "exec")
    commands = []
    outer_sessions = []
    factory = sessionmaker(bind=metadata.bind)
    scoped = scoped_session(factory)

    # SQLite does not implement the PostgreSQL SET statements. Intercept only
    # these two commands while exercising real engine begin events and sessions.
    @event.listens_for(metadata.bind, "before_cursor_execute", retval=True)
    def postgres_settings(_connection, _cursor, statement, parameters, _context, _many):
        if statement.startswith("SET "):
            commands.append(statement)
            return "SELECT 1", ()
        return statement, parameters

    @contextmanager
    def create_session(*, scoped=True):
        print(CANARY, file=sys.stderr)
        session = scoped_factory() if scoped else factory()
        if not scoped:
            outer_sessions.append(session)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    scoped_factory = scoped

    class NestedSessionReader(SyntheticReader):
        def read_log_chunks(self, task, try_number, metadata):
            # Mirrors FileTaskHandler._render_filename's @provide_session:
            # its own scoped session commits/closes during each log read.
            with create_session() as inner:
                inner.execute(text("SELECT 1"))
                assert inner is not outer_sessions[0]
            assert outer_sessions[0].in_transaction()
            return super().read_log_chunks(task, try_number, metadata)

    reader = NestedSessionReader()

    def noisy_reader():
        print(CANARY)
        os.write(2, CANARY.encode())
        logging.critical(CANARY)
        return reader

    modules = {
        "airflow": SimpleNamespace(settings=SimpleNamespace(engine=metadata.bind)),
        "airflow.models.dagrun": SimpleNamespace(DagRun=DagRun),
        "airflow.models.taskinstance": SimpleNamespace(TaskInstance=TaskInstance),
        "airflow.utils.session": SimpleNamespace(create_session=create_session),
        "airflow.utils.log.log_reader": SimpleNamespace(TaskLogReader=noisy_reader),
    }
    original_import = builtins.__import__

    def noisy_import(name, *args, **kwargs):
        if name in modules:
            print(CANARY)
            os.write(1, CANARY.encode())
            return modules[name]
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(sys, "argv", ["-", COMMIT, COMMIT])
    monkeypatch.setenv("DEPLOYMENT_COMMIT", COMMIT)
    with monkeypatch.context() as imports:
        imports.setattr(builtins, "__import__", noisy_import)
        exec(code, {})
    captured = capfd.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    assert not any(private in captured.out for private in PRIVATE_VALUES)
    report = probe.parse_remote_result(captured.out, COMMIT)
    assert report["ok"] is True
    assert report["all_recent_runs_successful"] is False
    assert len(outer_sessions) == 1
    assert commands == ["SET TRANSACTION READ ONLY", "SET LOCAL statement_timeout = 5000"] * 20
    assert len(reader.calls) == 19


def test_remote_shell_compiles_and_does_not_offer_arbitrary_selectors():
    result = subprocess.run(
        ["bash", "-n"], input=probe.remote_script(), text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    compile(probe.remote_python(), "<remote-crland-diagnostic>", "exec")


@pytest.mark.parametrize("returncode,expected_exit", [(0, None), (1, 1), (124, 1)])
def test_cli_keeps_failure_evidence_without_leaking_transport_output(
    complete_report, monkeypatch, capsys, returncode, expected_exit
):
    remote = {
        "host": "example.invalid",
        "port": "22",
        "username": "synthetic",
        "repository_path": "/srv/synthetic repo",
    }
    monkeypatch.setattr(probe, "airflow_remote", lambda: remote)
    stdout = CANARY + "\n" + probe.RESULT_MARKER + json.dumps(complete_report) + "\n" + CANARY
    run = Mock(return_value=SimpleNamespace(returncode=returncode, stdout=stdout, stderr=CANARY))
    monkeypatch.setattr(probe, "run", run)
    monkeypatch.setattr(sys, "argv", ["diagnose", "--expected-commit", COMMIT, "--format", "json"])
    if expected_exit is None:
        probe.main()
    else:
        with pytest.raises(SystemExit) as error:
            probe.main()
        assert error.value.code == expected_exit
    captured = capsys.readouterr()
    assert CANARY not in captured.out + captured.err
    report = json.loads(captured.out)
    assert report["ok"] is (returncode == 0)
    assert report["all_recent_runs_successful"] is False
    assert len(report["dags"]) == 2
    assert run.call_args.args[0][:2] == ["timeout", "180s"]
    assert run.call_args.kwargs["check"] is False


@pytest.mark.parametrize(
    "arguments,exit_code",
    [
        (["--expected-commit", CANARY], 1),
        (["--expected-commit", COMMIT, "--dag", CANARY], 2),
        (["--expected-commit", COMMIT, "--log-path", CANARY], 2),
        (["--expected-commit", COMMIT, "--shell", CANARY], 2),
    ],
)
def test_invalid_or_value_bearing_cli_inputs_never_reach_ssh(
    arguments, exit_code, monkeypatch, capsys
):
    remote = Mock()
    monkeypatch.setattr(probe, "airflow_remote", remote)
    monkeypatch.setattr(sys, "argv", ["diagnose", *arguments])
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == exit_code
    remote.assert_not_called()
    captured = capsys.readouterr()
    assert CANARY not in captured.out + captured.err
    assert json.loads(captured.out)["ok"] is False


@pytest.mark.parametrize(
    "output,reason",
    [
        (CANARY, "remote_output_missing"),
        (probe.RESULT_MARKER + CANARY, "remote_output_invalid"),
        (probe.RESULT_MARKER + '{"schema_version":true,"read_only":true}', "remote_output_invalid"),
    ],
)
def test_unavailable_or_invalid_remote_output_is_safe(output, reason):
    report = probe.parse_remote_result(output, COMMIT)
    assert report["ok"] is False
    assert reason in report["missing_evidence"]
    assert CANARY not in json.dumps(report)
