from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from .domain import VENUES, utc_now
from .schema import SCHEMA_STATEMENTS, SCHEMA_VERSION

_ENGINE: Engine | None = None
_ENGINE_LOCK = threading.Lock()
_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def _database_url() -> str:
    configured = os.environ.get("ZACKS_DATABASE_URL", "").strip()
    if configured:
        return configured
    try:
        from airflow.configuration import conf

        return str(conf.get("database", "sql_alchemy_conn"))
    except Exception as exc:
        raise RuntimeError(
            "ZACKS_DATABASE_URL is required outside the Airflow runtime"
        ) from exc


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


def ensure_schema(engine: Engine | None = None, *, force: bool = False) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY and not force:
        return
    target = engine or get_engine()
    with _SCHEMA_LOCK:
        if _SCHEMA_READY and not force:
            return
        with target.begin() as connection:
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('zacks-host-schema-v1'))"))
            for statement in SCHEMA_STATEMENTS:
                connection.execute(text(statement))
            connection.execute(
                text(
                    """
                    INSERT INTO zacks.schema_versions(version, applied_at)
                    VALUES (:version, now())
                    ON CONFLICT (version) DO NOTHING
                    """
                ),
                {"version": SCHEMA_VERSION},
            )
            now = utc_now()
            for venue_id, venue_name in VENUES.items():
                connection.execute(
                    text(
                        """
                        INSERT INTO zacks.venue_status(
                            venue_id, venue_name, healthy, updated_at
                        )
                        VALUES (:venue_id, :venue_name, false, :updated_at)
                        ON CONFLICT (venue_id) DO UPDATE SET
                            venue_name = EXCLUDED.venue_name
                        """
                    ),
                    {
                        "venue_id": venue_id,
                        "venue_name": venue_name,
                        "updated_at": now,
                    },
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO zacks.subscription_generations(
                            venue_id, generation, updated_at
                        )
                        VALUES (:venue_id, 0, :updated_at)
                        ON CONFLICT (venue_id) DO NOTHING
                        """
                    ),
                    {"venue_id": venue_id, "updated_at": now},
                )
        _SCHEMA_READY = True


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
        row = connection.execute(
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
            {"version": SCHEMA_VERSION},
        ).mappings().one()
    return dict(row)


def reset_engine_for_test() -> None:
    global _ENGINE, _SCHEMA_READY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SCHEMA_READY = False
