from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from weakref import WeakSet

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from .domain import VENUES, utc_now
from .schema import SCHEMA_STATEMENTS, SCHEMA_VERSION
from .schema_extensions import SCHEMA_EXTENSION_STATEMENTS

_ENGINE: Engine | None = None
_ENGINE_LOCK = threading.Lock()
_SCHEMA_ENGINES: WeakSet[Engine] = WeakSet()
_SCHEMA_LOCK = threading.Lock()
# Include extensions and catalog seeds: the old semantic version alone did not
# change when extension DDL changed. Persist this only with a successful commit.
SCHEMA_REVISION = (
    SCHEMA_VERSION
    + ":"
    + hashlib.sha256(
        json.dumps(
            [SCHEMA_STATEMENTS, SCHEMA_EXTENSION_STATEMENTS, sorted(VENUES.items())],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
)
SCHEMA_ATTEMPTS = 5


def _database_url() -> str:
    configured = os.environ.get("ZACKS_DATABASE_URL", "").strip()
    if configured:
        return configured
    try:
        from airflow.configuration import conf

        return str(conf.get("database", "sql_alchemy_conn"))
    except Exception as exc:
        raise RuntimeError("ZACKS_DATABASE_URL is required outside the Airflow runtime") from exc


def get_engine() -> Engine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = create_engine(
                _database_url(),
                pool_pre_ping=True,
                pool_recycle=1_800,
                pool_size=5,
                max_overflow=5,
                future=True,
            )
    return _ENGINE


def _schema_current(connection: Connection) -> bool:
    if connection.execute(text("SELECT to_regclass('zacks.schema_versions')")).scalar_one() is None:
        return False
    return bool(
        connection.execute(
            text("SELECT EXISTS (SELECT 1 FROM zacks.schema_versions WHERE version=:version)"),
            {"version": SCHEMA_REVISION},
        ).scalar_one()
    )


def _apply_schema(connection: Connection) -> None:
    for statement in (*SCHEMA_STATEMENTS, *SCHEMA_EXTENSION_STATEMENTS):
        connection.execute(text(statement))
    now = utc_now()
    for venue_id, venue_name in sorted(VENUES.items()):
        connection.execute(
            text(
                """
                INSERT INTO zacks.venue_status(venue_id, venue_name, healthy, updated_at)
                VALUES (:venue_id, :venue_name, false, :updated_at)
                ON CONFLICT (venue_id) DO UPDATE SET venue_name = EXCLUDED.venue_name
                """
            ),
            {"venue_id": venue_id, "venue_name": venue_name, "updated_at": now},
        )
        connection.execute(
            text(
                """
                INSERT INTO zacks.subscription_generations(venue_id, generation, updated_at)
                VALUES (:venue_id, 0, :updated_at)
                ON CONFLICT (venue_id) DO NOTHING
                """
            ),
            {"venue_id": venue_id, "updated_at": now},
        )
    connection.execute(
        text(
            "INSERT INTO zacks.schema_versions(version, applied_at) VALUES (:version, now()) "
            "ON CONFLICT (version) DO NOTHING"
        ),
        [{"version": SCHEMA_VERSION}, {"version": SCHEMA_REVISION}],
    )


def _ensure_schema_once(target: Engine, *, force: bool) -> None:
    with target.begin() as connection:
        # One cold process must never hold application tables indefinitely while
        # other processes serve observations. Retry only rolled-back lock errors.
        connection.execute(text("SET LOCAL lock_timeout = '5s'"))
        connection.execute(text("SET LOCAL statement_timeout = '60s'"))
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('zacks-host-schema-v1'))"))
        if force or not _schema_current(connection):
            _apply_schema(connection)


def ensure_schema(engine: Engine | None = None, *, force: bool = False) -> None:
    target = engine or get_engine()
    with _SCHEMA_LOCK:
        if target in _SCHEMA_ENGINES and not force:
            return
        _SCHEMA_ENGINES.discard(target)
        for attempt in range(SCHEMA_ATTEMPTS):
            try:
                _ensure_schema_once(target, force=force)
                break
            except DBAPIError as exc:
                code = getattr(exc.orig, "pgcode", None) or getattr(exc.orig, "sqlstate", None)
                if code not in {"40P01", "55P03"} or attempt == SCHEMA_ATTEMPTS - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))
        # Cache by engine, and only AFTER transaction commit. A new CLI process
        # reads the durable fingerprint instead of rerunning CREATE INDEX/ALTER.
        _SCHEMA_ENGINES.add(target)


@contextmanager
def transaction(engine: Engine | None = None) -> Iterator[Connection]:
    target = engine or get_engine()
    ensure_schema(target)
    with target.begin() as connection:
        yield connection


def ping(engine: Engine | None = None) -> dict[str, Any]:
    target = engine or get_engine()
    ensure_schema(target)
    with target.connect() as connection:
        row = (
            connection.execute(
                text(
                    """
                SELECT
                    current_database() AS database_name,
                    current_setting('server_version_num')::integer AS server_version_num,
                    EXISTS (
                        SELECT 1 FROM zacks.schema_versions WHERE version = :version
                    ) AS schema_ready
                """
                ),
                {"version": SCHEMA_REVISION},
            )
            .mappings()
            .one()
        )
    return dict(row)


def reset_engine_for_test() -> None:
    global _ENGINE
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SCHEMA_ENGINES.clear()
