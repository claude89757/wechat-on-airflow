#!/usr/bin/env python3
"""Bounded, read-only CRLand task evidence for the protected Airflow workflow."""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import os
import re
import shlex
import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from typing import Any

from _ops import airflow_remote, emit, run, ssh_command

DAGS = {
    "szw": ("深圳湾网球场巡检", 4),
    "gba": ("大湾区网球场巡检", 3),
}
RUN_COUNT = 3
MAX_LOG_RECORDS = 400
MAX_RECORD_LENGTH = 4096
LOG_READ_SECONDS = 5
COLLECTION_SECONDS = 120
RESULT_MARKER = "__CRLAND_INSPECTION_DIAGNOSTIC_V1__"
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})"
)
STATES = frozenset(
    {
        "success",
        "failed",
        "skipped",
        "upstream_failed",
        "removed",
        "running",
        "queued",
        "scheduled",
        "deferred",
        "up_for_retry",
        "up_for_reschedule",
        "restarting",
    }
)
ERROR_TYPES = frozenset(
    {
        "ReadTimeout",
        "ConnectTimeout",
        "ConnectionError",
        "SSLError",
        "ProxyError",
        "Timeout",
        "TimeoutError",
        "HTTPError",
        "RequestException",
        "JSONDecodeError",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "OSError",
        "ImportError",
        "ModuleNotFoundError",
        "AttributeError",
        "RuntimeError",
        "OperationalError",
        "DatabaseError",
        "ProgrammingError",
        "AirflowFailException",
        "OtherError",
    }
)
METADATA_STAGES = frozenset({"query_runs", "query_tasks"})
METADATA_ERROR_TYPES = frozenset(
    {
        "OperationalError",
        "InterfaceError",
        "DatabaseError",
        "ProgrammingError",
        "InternalError",
        "DataError",
        "IntegrityError",
        "StatementError",
        "SQLAlchemyError",
        "InvalidRequestError",
        "PendingRollbackError",
        "DetachedInstanceError",
        "ResourceClosedError",
        "DisconnectionError",
        "TimeoutError",
        "ValueError",
        "TypeError",
        "AttributeError",
        "RuntimeError",
        "OtherError",
    }
)
METADATA_SQLSTATES = frozenset(
    {
        "08000",
        "08001",
        "08003",
        "08004",
        "08006",
        "08007",
        "08P01",
        "22000",
        "22P02",
        "25006",
        "25P02",
        "40001",
        "40P01",
        "42501",
        "42601",
        "42703",
        "42P01",
        "53300",
        "55P03",
        "57014",
        "57P01",
        "57P02",
        "57P03",
        "58000",
        "XX000",
    }
)
MISSING_REASONS = frozenset(
    {
        "invalid_arguments",
        "invalid_expected_commit",
        "git_commit_missing",
        "runtime_commit_missing",
        "commit_mismatch",
        "remote_failed",
        "remote_timeout",
        "remote_output_missing",
        "remote_output_invalid",
        "airflow_import_failed",
        "metadata_read_failed",
        "not_enough_scheduled_runs",
        "run_timestamp_missing",
        "task_instance_missing",
        "task_metadata_invalid",
        "log_reader_unavailable",
        "no_attempts",
        "no_log_records",
        "no_allowlisted_signals",
        "log_read_failed",
        "log_read_timeout",
        "log_read_truncated",
        "log_read_incomplete",
        "collection_time_limit",
        "failure_signature_missing",
    }
)
COUNTERS = (
    "api_success_count",
    "inspection_skipped_count",
    "legacy_single_count",
    "invalid_json_count",
)


def safe_commit(value: object) -> str | None:
    return value if isinstance(value, str) and COMMIT_PATTERN.fullmatch(value) else None


def safe_timestamp(value: object) -> str | None:
    if isinstance(value, str):
        if not TIMESTAMP_PATTERN.fullmatch(value):
            return None
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    try:
        return value.astimezone(UTC).isoformat()
    except (OverflowError, ValueError):
        return None


def safe_integer(value: object, maximum: int = 1_000_000) -> int | None:
    return value if type(value) is int and 0 <= value <= maximum else None


def safe_state(value: object) -> str | None:
    return value if isinstance(value, str) and value in STATES else None


def safe_error_type(error: object) -> str:
    name = type(error).__name__
    return name if name in ERROR_TYPES else "OtherError"


def safe_metadata_error(value: object) -> dict[str, Any] | None:
    """Keep fixed failure classifications, never SQL, parameters or error messages."""
    if not isinstance(value, dict):
        return None
    stage = value.get("stage")
    if not isinstance(stage, str) or stage not in METADATA_STAGES:
        return None
    exception_type = value.get("exception_type")
    if not isinstance(exception_type, str) or exception_type not in METADATA_ERROR_TYPES:
        exception_type = "OtherError"
    sqlstate = value.get("sqlstate")
    if not isinstance(sqlstate, str) or sqlstate not in METADATA_SQLSTATES:
        sqlstate = None
    kind = "unknown"
    if sqlstate == "57014":
        kind = (
            "statement_timeout"
            if value.get("metadata_error_kind") == "statement_timeout"
            else "query_canceled"
        )
    return {
        "stage": stage,
        "exception_type": exception_type,
        "sqlstate": sqlstate,
        "metadata_error_kind": kind,
    }


def classify_metadata_error(error: Exception, stage: str) -> dict[str, Any] | None:
    driver_error = getattr(error, "orig", error)
    sqlstate = next(
        (
            code
            for code in (
                getattr(driver_error, "sqlstate", None),
                getattr(driver_error, "pgcode", None),
            )
            if isinstance(code, str) and code in METADATA_SQLSTATES
        ),
        None,
    )
    primary_message = getattr(getattr(driver_error, "diag", None), "message_primary", None)
    return safe_metadata_error(
        {
            "stage": stage,
            "exception_type": type(error).__name__,
            "sqlstate": sqlstate,
            "metadata_error_kind": (
                "statement_timeout"
                if sqlstate == "57014"
                and primary_message == "canceling statement due to statement timeout"
                else "unknown"
            ),
        }
    )


def missing_reasons(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item in MISSING_REASONS})


@contextmanager
def quiet_runtime() -> Iterator[None]:
    """Discard SDK/import output, including handlers holding the original file descriptors."""
    previous_disable = logging.root.manager.disable
    saved = (os.dup(1), os.dup(2))
    try:
        with open(os.devnull, "w", encoding="utf-8") as sink:
            os.dup2(sink.fileno(), 1)
            os.dup2(sink.fileno(), 2)
            with redirect_stdout(sink), redirect_stderr(sink):
                logging.disable(100)
                try:
                    yield
                finally:
                    logging.disable(previous_disable)
    finally:
        for descriptor, original in zip((1, 2), saved, strict=True):
            os.dup2(original, descriptor)
            os.close(original)


class LogReadDeadline(BaseException):
    """Escape the log SDK's broad Exception handlers without emitting their payloads."""


def raise_log_timeout(_signum: int, _frame: object) -> None:
    raise LogReadDeadline


@contextmanager
def log_read_deadline() -> Iterator[None]:
    handler = signal.signal(signal.SIGALRM, raise_log_timeout)
    timer = signal.setitimer(signal.ITIMER_REAL, LOG_READ_SECONDS)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *timer)
        signal.signal(signal.SIGALRM, handler)


def empty_attempt(try_number: int) -> dict[str, Any]:
    return {
        "try_number": try_number,
        "log_records_examined": 0,
        "end_of_log": False,
        "rotation_selections": [],
        **{key: 0 for key in COUNTERS},
        "http_status_codes": [],
        "api_error_codes": [],
        "exception_types": [],
        "missing_evidence": [],
    }


def finish_attempt(result: dict[str, Any]) -> dict[str, Any]:
    """Derive completeness from evidence, including after remote-output filtering."""
    if not result["log_records_examined"]:
        result["missing_evidence"].append("no_log_records")
    if not result["end_of_log"]:
        result["missing_evidence"].append("log_read_incomplete")
    if not any(
        result[key]
        for key in (
            *COUNTERS,
            "rotation_selections",
            "http_status_codes",
            "api_error_codes",
            "exception_types",
        )
    ):
        result["missing_evidence"].append("no_allowlisted_signals")
    for key in ("http_status_codes", "api_error_codes", "exception_types", "missing_evidence"):
        result[key] = sorted(set(result[key]))[:20]
    return result


def has_failure_signature(attempts: list[dict[str, Any]]) -> bool:
    return any(
        evidence["api_error_codes"]
        or evidence["exception_types"]
        or evidence["invalid_json_count"]
        or any(status >= 400 for status in evidence["http_status_codes"])
        for evidence in attempts
    )


def extract_log_signal(event: object, result: dict[str, Any]) -> None:
    """Match whole known messages; never return log text or arbitrary captured strings."""
    if not isinstance(event, str) or len(event) > MAX_RECORD_LENGTH:
        return
    match = re.fullmatch(
        r"CRLand authorization: mode=rotation slot=([1-3])/3 "
        r"round_minute_utc=(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\+00:00)"
        r"(?: interval_minutes=([1-3]))?",
        event,
    )
    if match and safe_timestamp(match[2]):
        selection = {
            "slot": int(match[1]),
            "round_minute_utc": match[2],
            "interval_minutes": int(match[3]) if match[3] else None,
        }
        if (
            selection not in result["rotation_selections"]
            and len(result["rotation_selections"]) < 4
        ):
            result["rotation_selections"].append(selection)
        return
    if event == "CRLand authorization: mode=legacy-single":
        result["legacy_single_count"] += 1
    elif event == "api success":
        result["api_success_count"] += 1
    elif event == "invalid json response":
        result["invalid_json_count"] += 1
    elif re.fullmatch(
        r"Day [0-3]: (?:每天0点-8点不巡检|仅在北京时间08:00–21:00巡检，本轮不查询场地)", event
    ):
        result["inspection_skipped_count"] += 1
    else:
        status = re.fullmatch(r"response status_code: ([1-5]\d{2})", event)
        if status:
            result["http_status_codes"].append(int(status[1]))
            return
        error = re.fullmatch(
            r"(?:failed for 不使用代理: |api error for 不使用代理: |"
            r"Error checking date \d{4}-\d{2}-\d{2}: all attempts failed: )"
            r"(?:(http status code)=([1-5]\d{2})|(api error code)=(\d{1,9})|"
            r"request failed \(([A-Za-z]+)\))",
            event,
        )
        if error:
            if error[1]:
                result["http_status_codes"].append(int(error[2]))
            elif error[3]:
                # code=200 with an empty result is a genuine business-error observation.
                result["api_error_codes"].append(int(error[4]))
            elif error[5] in ERROR_TYPES:
                result["exception_types"].append(error[5])


def collect_attempt(reader: Any, task: Any, try_number: int) -> dict[str, Any]:
    result = empty_attempt(try_number)
    try:
        with log_read_deadline():
            stream, metadata = reader.read_log_chunks(task, try_number, {"end_of_log": False})
            for index, record in enumerate(stream):
                if index >= MAX_LOG_RECORDS:
                    result["missing_evidence"].append("log_read_truncated")
                    break
                result["log_records_examined"] += 1
                extract_log_signal(getattr(record, "event", None), result)
            result["end_of_log"] = isinstance(metadata, dict) and metadata.get("end_of_log") is True
    except LogReadDeadline:
        result["exception_types"].append("TimeoutError")
        result["missing_evidence"].append("log_read_timeout")
    except Exception as error:
        result["exception_types"].append(safe_error_type(error))
        result["missing_evidence"].append(
            "log_read_timeout" if isinstance(error, TimeoutError) else "log_read_failed"
        )
    return finish_attempt(result)


def scheduled_runs(session: Any, dag_run_model: Any, dag_id: str) -> list[Any]:
    # Exclude undated runs and retain the ordering supported by Airflow's
    # existing (dag_id, logical_date) index; no schema or timeout change.
    return (
        session.query(dag_run_model)
        .filter(
            dag_run_model.dag_id == dag_id,
            dag_run_model.run_type == "scheduled",
            dag_run_model.state.in_(("success", "failed")),
            dag_run_model.logical_date.is_not(None),
        )
        .order_by(dag_run_model.logical_date.desc(), dag_run_model.id.desc())
        .limit(RUN_COUNT)
        .all()
    )


def collect_dags(
    session: Any, dag_run_model: Any, task_model: Any, reader: Any
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + COLLECTION_SECONDS
    dags = []
    for venue_id, (dag_id, task_count) in DAGS.items():
        dag = {
            "venue_id": venue_id,
            "dag_id": dag_id,
            "runs": [],
            "metadata_error": None,
            "missing_evidence": [],
        }
        dags.append(dag)
        task_ids = [f"check_and_notify_day_{offset}" for offset in range(task_count)]
        stage = "query_runs"
        try:
            recent = scheduled_runs(session, dag_run_model, dag_id)
            if len(recent) < RUN_COUNT:
                dag["missing_evidence"].append("not_enough_scheduled_runs")
            for dag_run in recent:
                stage = "query_runs"
                row = {
                    "run_type": "scheduled",
                    "state": safe_state(dag_run.state),
                    "logical_date": safe_timestamp(dag_run.logical_date),
                    "data_interval_start": safe_timestamp(dag_run.data_interval_start),
                    "data_interval_end": safe_timestamp(dag_run.data_interval_end),
                    "started_at": safe_timestamp(dag_run.start_date),
                    "ended_at": safe_timestamp(dag_run.end_date),
                    "tasks": [],
                    "missing_evidence": [],
                }
                dag["runs"].append(row)
                if any(
                    row[key] is None
                    for key in (
                        "logical_date",
                        "data_interval_start",
                        "data_interval_end",
                        "started_at",
                        "ended_at",
                    )
                ):
                    row["missing_evidence"].append("run_timestamp_missing")
                stage = "query_tasks"
                tasks = (
                    session.query(task_model)
                    .filter(
                        task_model.dag_id == dag_id,
                        task_model.run_id == dag_run.run_id,
                        task_model.task_id.in_(task_ids),
                        task_model.map_index == -1,
                    )
                    .all()
                )
                by_id = {task.task_id: task for task in tasks}
                for task_id in task_ids:
                    task = by_id.get(task_id)
                    item = {
                        "task_id": task_id,
                        "state": None,
                        "try_number": None,
                        "attempts": [],
                        "missing_evidence": [],
                    }
                    row["tasks"].append(item)
                    if task is None:
                        item["missing_evidence"].append("task_instance_missing")
                        continue
                    item.update(
                        {
                            "state": safe_state(task.state),
                            "try_number": safe_integer(task.try_number),
                            "started_at": safe_timestamp(task.start_date),
                            "ended_at": safe_timestamp(task.end_date),
                        }
                    )
                    if item["state"] is None or item["try_number"] is None:
                        item["missing_evidence"].append("task_metadata_invalid")
                        continue
                    latest = item["try_number"]
                    if latest < 1:
                        item["missing_evidence"].append("no_attempts")
                        continue
                    if reader is None:
                        item["missing_evidence"].append("log_reader_unavailable")
                        continue
                    first = max(1, latest - 1) if item["state"] == "failed" else latest
                    for attempt in range(first, latest + 1):
                        if time.monotonic() >= deadline:
                            item["missing_evidence"].append("collection_time_limit")
                            break
                        item["attempts"].append(collect_attempt(reader, task, attempt))
                    if item["state"] == "failed" and not has_failure_signature(item["attempts"]):
                        item["missing_evidence"].append("failure_signature_missing")
        except Exception as error:
            dag["missing_evidence"].append("metadata_read_failed")
            dag["metadata_error"] = classify_metadata_error(error, stage)
    return dags


def base_report(expected_commit: object = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "read_only": True,
        "ok": False,
        "expected_commit": safe_commit(expected_commit),
        "deployed_commit": None,
        "runtime_commit": None,
        "commit_matches": False,
        "evidence_complete": False,
        "all_recent_runs_successful": False,
        "missing_evidence": [],
        "dags": [],
    }


def read_only_transaction(connection: Any) -> None:
    """Apply to every transaction in this process, including log-reader inner sessions."""
    connection.exec_driver_sql("SET TRANSACTION READ ONLY")
    connection.exec_driver_sql("SET LOCAL statement_timeout = 5000")


def sanitize_report(value: object, expected_commit: object) -> dict[str, Any]:
    """Rebuild the entire output from bounded allowlists, even for remote JSON."""
    result = base_report(expected_commit)
    if (
        not isinstance(value, dict)
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != 1
        or value.get("read_only") is not True
    ):
        result["missing_evidence"] = ["remote_output_invalid"]
        return result
    for key in ("deployed_commit", "runtime_commit"):
        result[key] = safe_commit(value.get(key))
    result["missing_evidence"] = missing_reasons(value.get("missing_evidence"))
    if result["expected_commit"] is None:
        result["missing_evidence"].append("invalid_expected_commit")
    if result["deployed_commit"] is None:
        result["missing_evidence"].append("git_commit_missing")
    if result["runtime_commit"] is None:
        result["missing_evidence"].append("runtime_commit_missing")
    result["commit_matches"] = bool(
        result["expected_commit"]
        and result["expected_commit"] == result["deployed_commit"] == result["runtime_commit"]
    )
    if not result["commit_matches"]:
        result["missing_evidence"].append("commit_mismatch")
    candidates = value.get("dags") if isinstance(value.get("dags"), list) else []
    for venue_id, (dag_id, task_count) in DAGS.items():
        source = next(
            (
                d
                for d in candidates
                if isinstance(d, dict)
                and d.get("venue_id") == venue_id
                and d.get("dag_id") == dag_id
            ),
            {},
        )
        dag = {
            "venue_id": venue_id,
            "dag_id": dag_id,
            "runs": [],
            "metadata_error": safe_metadata_error(source.get("metadata_error")),
            "missing_evidence": missing_reasons(source.get("missing_evidence")),
        }
        if source.get("metadata_error") is not None:
            dag["missing_evidence"].append("metadata_read_failed")
        result["dags"].append(dag)
        sources = source.get("runs") if isinstance(source.get("runs"), list) else []
        for source_run in sources[:RUN_COUNT]:
            if (
                not isinstance(source_run, dict)
                or source_run.get("run_type") != "scheduled"
                or safe_state(source_run.get("state")) not in {"success", "failed"}
            ):
                continue
            row = {
                "run_type": "scheduled",
                "state": source_run["state"],
                "tasks": [],
                "missing_evidence": missing_reasons(source_run.get("missing_evidence")),
            }
            for key in (
                "logical_date",
                "data_interval_start",
                "data_interval_end",
                "started_at",
                "ended_at",
            ):
                row[key] = safe_timestamp(source_run.get(key))
                if row[key] is None:
                    row["missing_evidence"].append("run_timestamp_missing")
            dag["runs"].append(row)
            tasks = source_run.get("tasks") if isinstance(source_run.get("tasks"), list) else []
            for offset in range(task_count):
                task_id = f"check_and_notify_day_{offset}"
                task = next(
                    (t for t in tasks if isinstance(t, dict) and t.get("task_id") == task_id), {}
                )
                item = {
                    "task_id": task_id,
                    "state": safe_state(task.get("state")),
                    "try_number": safe_integer(task.get("try_number")),
                    "attempts": [],
                    "missing_evidence": missing_reasons(task.get("missing_evidence")),
                }
                for key in ("started_at", "ended_at"):
                    item[key] = safe_timestamp(task.get(key))
                row["tasks"].append(item)
                if not task:
                    item["missing_evidence"].append("task_instance_missing")
                if item["state"] is None or item["try_number"] is None:
                    item["missing_evidence"].append("task_metadata_invalid")
                attempts = task.get("attempts") if isinstance(task.get("attempts"), list) else []
                latest = item["try_number"] or 0
                allowed_tries = (
                    {latest, max(1, latest - 1)} if item["state"] == "failed" else {latest}
                )
                for attempt in attempts[-2:]:
                    if (
                        not isinstance(attempt, dict)
                        or not safe_integer(attempt.get("try_number"))
                        or attempt["try_number"] not in allowed_tries
                    ):
                        continue
                    evidence = empty_attempt(attempt["try_number"])
                    evidence["log_records_examined"] = (
                        safe_integer(attempt.get("log_records_examined"), MAX_LOG_RECORDS) or 0
                    )
                    evidence["end_of_log"] = attempt.get("end_of_log") is True
                    evidence["missing_evidence"] = missing_reasons(attempt.get("missing_evidence"))
                    for key in COUNTERS:
                        evidence[key] = safe_integer(attempt.get(key), MAX_LOG_RECORDS) or 0
                    for key, maximum in (
                        ("http_status_codes", 599),
                        ("api_error_codes", 999_999_999),
                    ):
                        numbers = attempt.get(key) if isinstance(attempt.get(key), list) else []
                        evidence[key] = sorted(
                            {
                                n
                                for n in numbers
                                if safe_integer(n, maximum) is not None
                                and (key != "http_status_codes" or n >= 100)
                            }
                        )[:20]
                    errors = (
                        attempt.get("exception_types")
                        if isinstance(attempt.get("exception_types"), list)
                        else []
                    )
                    evidence["exception_types"] = sorted(
                        {e for e in errors if isinstance(e, str) and e in ERROR_TYPES}
                    )[:20]
                    selections = (
                        attempt.get("rotation_selections")
                        if isinstance(attempt.get("rotation_selections"), list)
                        else []
                    )
                    for selection in selections[:4]:
                        if (
                            not isinstance(selection, dict)
                            or type(selection.get("slot")) is not int
                            or selection["slot"] not in (1, 2, 3)
                        ):
                            continue
                        timestamp = safe_timestamp(selection.get("round_minute_utc"))
                        interval = selection.get("interval_minutes")
                        if timestamp is None or (
                            interval is not None
                            and (type(interval) is not int or interval not in (1, 2, 3))
                        ):
                            continue
                        evidence["rotation_selections"].append(
                            {
                                "slot": selection["slot"],
                                "round_minute_utc": datetime.fromisoformat(timestamp).isoformat(
                                    timespec="minutes"
                                ),
                                "interval_minutes": interval,
                            }
                        )
                    item["attempts"].append(finish_attempt(evidence))
                if not any(evidence["try_number"] == latest for evidence in item["attempts"]):
                    item["missing_evidence"].append("no_attempts")
                if item["state"] == "failed" and not has_failure_signature(item["attempts"]):
                    item["missing_evidence"].append("failure_signature_missing")
        if len(dag["runs"]) != RUN_COUNT:
            dag["missing_evidence"].append("not_enough_scheduled_runs")
    missing = result["missing_evidence"]
    for dag in result["dags"]:
        missing.extend(dag["missing_evidence"])
        for row in dag["runs"]:
            missing.extend(row["missing_evidence"])
            for task in row["tasks"]:
                missing.extend(task["missing_evidence"])
                for attempt in task["attempts"]:
                    missing.extend(attempt["missing_evidence"])
    result["missing_evidence"] = sorted(set(missing))
    result["evidence_complete"] = not result["missing_evidence"]
    result["all_recent_runs_successful"] = all(
        len(dag["runs"]) == RUN_COUNT and all(row["state"] == "success" for row in dag["runs"])
        for dag in result["dags"]
    )
    result["ok"] = result["commit_matches"] and result["evidence_complete"]
    return result


def remote_python() -> str:
    imports = """from __future__ import annotations
import json, logging, os, re, signal, sys, time
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from typing import Any
"""
    constants = (
        "DAGS",
        "RUN_COUNT",
        "MAX_LOG_RECORDS",
        "MAX_RECORD_LENGTH",
        "LOG_READ_SECONDS",
        "COLLECTION_SECONDS",
        "RESULT_MARKER",
        "STATES",
        "ERROR_TYPES",
        "METADATA_STAGES",
        "METADATA_ERROR_TYPES",
        "METADATA_SQLSTATES",
        "MISSING_REASONS",
        "COUNTERS",
    )
    code = imports + "\n".join(f"{name} = {globals()[name]!r}" for name in constants) + "\n"
    code += f"COMMIT_PATTERN = re.compile({COMMIT_PATTERN.pattern!r})\nTIMESTAMP_PATTERN = re.compile({TIMESTAMP_PATTERN.pattern!r})\n"
    helpers = (
        safe_commit,
        safe_timestamp,
        safe_integer,
        safe_state,
        safe_error_type,
        safe_metadata_error,
        classify_metadata_error,
        missing_reasons,
        quiet_runtime,
        LogReadDeadline,
        raise_log_timeout,
        log_read_deadline,
        empty_attempt,
        finish_attempt,
        has_failure_signature,
        extract_log_signal,
        collect_attempt,
        scheduled_runs,
        collect_dags,
        base_report,
        read_only_transaction,
        sanitize_report,
    )
    code += "\n\n".join(inspect.getsource(helper) for helper in helpers)
    code += """
report = base_report(sys.argv[1])
report['deployed_commit'] = safe_commit(sys.argv[2])
report['runtime_commit'] = safe_commit(os.environ.get('DEPLOYMENT_COMMIT'))
with quiet_runtime():
    try:
        from airflow import settings
        from sqlalchemy import event
        event.listen(settings.engine, 'begin', read_only_transaction)
        from airflow.models.dagrun import DagRun
        from airflow.models.taskinstance import TaskInstance
        from airflow.utils.session import create_session
    except Exception:
        report['missing_evidence'].append('airflow_import_failed')
    else:
        try:
            from airflow.utils.log.log_reader import TaskLogReader
            reader = TaskLogReader()
        except Exception:
            reader = None
        try:
            with create_session(scoped=False) as session:
                report['dags'] = collect_dags(session, DagRun, TaskInstance, reader)
        except Exception:
            report['missing_evidence'].append('metadata_read_failed')
report = sanitize_report(report, sys.argv[1])
print(RESULT_MARKER + json.dumps(report, ensure_ascii=False, sort_keys=True))
"""
    return code


def remote_script() -> str:
    return (
        r"""set -eu
cd "$1"
expected_commit="$2"
deployed_commit="$(git rev-parse HEAD 2>/dev/null || true)"
compose() {
    if docker compose version >/dev/null 2>&1; then docker compose "$@";
    else docker-compose "$@"; fi
}
service="$(compose ps --services --status running | awk '/^airflow-api-server$|^web$/{print; exit}')"
test -n "$service"
compose exec -T "$service" sh -c '
    if [ -x /opt/bitnami/airflow/venv/bin/python ]; then
        exec /opt/bitnami/airflow/venv/bin/python "$@"
    fi
    exec python "$@"
' sh - "$expected_commit" "$deployed_commit" <<'PY'
"""
        + remote_python()
        + "\nPY\n"
    )


def parse_remote_result(output: str, expected_commit: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        if not line.startswith(RESULT_MARKER):
            continue
        try:
            return sanitize_report(json.loads(line[len(RESULT_MARKER) :]), expected_commit)
        except (ValueError, TypeError, KeyError, AttributeError):
            result = base_report(expected_commit)
            result["missing_evidence"] = ["remote_output_invalid"]
            return result
    result = base_report(expected_commit)
    result["missing_evidence"] = ["remote_output_missing"]
    return result


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        result = base_report()
        result["missing_evidence"] = ["invalid_arguments"]
        emit(result, "json")
        raise SystemExit(2)


def main() -> None:
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--format", choices=("text", "json"), default="json")
    args = parser.parse_args()
    report = base_report(args.expected_commit)
    if report["expected_commit"] is None:
        report["missing_evidence"] = ["invalid_expected_commit"]
    else:
        try:
            remote = airflow_remote()
            completed = run(
                [
                    "timeout",
                    "180s",
                    *ssh_command(remote),
                    "bash",
                    "-s",
                    "--",
                    shlex.quote(remote["repository_path"]),
                    args.expected_commit,
                ],
                check=False,
                input_text=remote_script(),
            )
            report = parse_remote_result(completed.stdout, args.expected_commit)
            if completed.returncode:
                report["missing_evidence"] = sorted(
                    set(report["missing_evidence"])
                    | {"remote_timeout" if completed.returncode == 124 else "remote_failed"}
                )
                report["ok"] = report["evidence_complete"] = False
        except Exception:
            report["missing_evidence"] = ["remote_failed"]
    emit(report, args.format)
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
