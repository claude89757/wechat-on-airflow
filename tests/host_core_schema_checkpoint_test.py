"""Startup/lock regressions, against an isolated PostgreSQL database only."""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from wechat_airflow.host_core import database

URL = os.environ.get("ZACKS_TEST_DATABASE_URL", "")


@pytest.fixture
def pg(monkeypatch):
    if not URL:
        pytest.skip("isolated PostgreSQL test URL not supplied")
    url = make_url(URL)
    if url.database != "zacks_test" or url.host not in {"localhost", "127.0.0.1", "postgres"}:
        pytest.fail("Refusing schema fixture outside isolated zacks_test")
    monkeypatch.setenv("ZACKS_DATABASE_URL", URL)
    database.reset_engine_for_test()
    engine = database.get_engine()
    with engine.begin() as connection:
        assert connection.execute(text("SELECT current_database()")).scalar_one() == "zacks_test"
        connection.execute(text("DROP SCHEMA IF EXISTS zacks CASCADE"))

    def forbidden(*args, **kwargs):
        raise AssertionError("external network is forbidden in PostgreSQL tests")

    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
    yield engine
    database.reset_engine_for_test()


def test_schema_fingerprint_is_durable_and_health_uses_it(pg):
    database.ensure_schema(pg)
    with pg.connect() as connection:
        versions = set(connection.execute(text("SELECT version FROM zacks.schema_versions")).scalars())
    assert {database.SCHEMA_VERSION, database.SCHEMA_REVISION} <= versions
    assert database.ping(pg)["schema_ready"] is True


def test_cold_process_does_not_issue_ddl_or_block_active_observation(pg):
    database.ensure_schema(pg)
    other = create_engine(URL)
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())

    event.listen(other, "before_cursor_execute", record)
    try:
        with pg.begin() as writer:
            # CREATE INDEX, including IF NOT EXISTS, needs a conflicting table
            # lock here. A cold CLI process must only read the fingerprint.
            writer.execute(text("LOCK TABLE zacks.observed_slots IN ROW EXCLUSIVE MODE"))
            with patch.object(database, "_apply_schema", side_effect=AssertionError("DDL on startup")):
                database.ensure_schema(other)
        assert statements
        assert not any(s.startswith(("CREATE", "ALTER", "INSERT", "UPDATE")) for s in statements)
        assert database.ping(other)["schema_ready"] is True
    finally:
        other.dispose()


def test_cache_is_per_engine_and_marker_loss_requires_migration(pg):
    database.ensure_schema(pg)
    with pg.begin() as connection:
        connection.execute(
            text("DELETE FROM zacks.schema_versions WHERE version=:version"),
            {"version": database.SCHEMA_REVISION},
        )
    other = create_engine(URL)
    try:
        with patch.object(database, "_apply_schema", wraps=database._apply_schema) as apply:
            database.ensure_schema(other)
        apply.assert_called_once()
        assert database.ping(other)["schema_ready"] is True
    finally:
        other.dispose()


def test_failed_schema_transaction_never_records_ready(pg):
    with patch.object(database, "_apply_schema", side_effect=RuntimeError("test rollback")):
        with pytest.raises(RuntimeError, match="test rollback"):
            database.ensure_schema(pg)
    assert pg not in database._SCHEMA_ENGINES
    with pg.connect() as connection:
        assert connection.execute(text("SELECT to_regclass('zacks.schema_versions')")).scalar_one() is None
    database.ensure_schema(pg)
    assert database.ping(pg)["schema_ready"] is True


@pytest.mark.parametrize("code", ["40P01", "55P03"])
def test_schema_lock_errors_retry_fresh_transactions(code):
    engine = create_engine("sqlite://")
    error = OperationalError("test", {}, Exception("synthetic lock failure"))
    error.orig = SimpleNamespace(pgcode=code)
    try:
        with (
            patch.object(database, "_ensure_schema_once", side_effect=[error, None]) as once,
            patch.object(database.time, "sleep") as sleep,
        ):
            database.ensure_schema(engine)
        assert once.call_count == 2
        sleep.assert_called_once_with(0.5)
        assert engine in database._SCHEMA_ENGINES
    finally:
        database._SCHEMA_ENGINES.discard(engine)
        engine.dispose()


def test_non_lock_error_is_not_retried_or_cached():
    engine = create_engine("sqlite://")
    error = OperationalError("test", {}, Exception("synthetic permission failure"))
    error.orig = SimpleNamespace(pgcode="42501")
    try:
        with (
            patch.object(database, "_ensure_schema_once", side_effect=error) as once,
            patch.object(database.time, "sleep") as sleep,
            pytest.raises(OperationalError),
        ):
            database.ensure_schema(engine)
        once.assert_called_once()
        sleep.assert_not_called()
        assert engine not in database._SCHEMA_ENGINES
    finally:
        engine.dispose()
