from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

from wechat_airflow.notification_core.config import NotificationCoreSettings, load_settings

_ENGINE: Engine | None = None
_ENGINE_LOCK = threading.Lock()
_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def engine(settings: NotificationCoreSettings | None = None) -> Engine:
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            resolved = settings or load_settings()
            _ENGINE = create_engine(
                resolved.database_url,
                pool_pre_ping=True,
                pool_size=5,
                max_overflow=5,
                pool_recycle=1800,
                future=True,
                connect_args={"application_name": "zacks-notification-core"},
            )
    return _ENGINE


def qualified_schema(settings: NotificationCoreSettings | None = None) -> str:
    resolved = settings or load_settings()
    schema = resolved.schema
    if not schema.replace("_", "").isalnum():
        raise RuntimeError("invalid notification core schema")
    return schema


def ensure_schema(settings: NotificationCoreSettings | None = None) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return
        resolved = settings or load_settings()
        schema = qualified_schema(resolved)
        sql_path = Path(__file__).with_name("schema.sql")
        script = sql_path.read_text(encoding="utf-8")
        if schema != "zacks_core":
            script = script.replace("zacks_core", schema)

        raw = engine(resolved).raw_connection()
        try:
            cursor = raw.cursor()
            try:
                cursor.execute("SELECT pg_advisory_lock(hashtext(%s))", (f"{schema}:migration",))
                cursor.execute(script)
                raw.commit()
            except Exception:
                raw.rollback()
                raise
            finally:
                with contextlib.suppress(Exception):
                    cursor.execute("SELECT pg_advisory_unlock(hashtext(%s))", (f"{schema}:migration",))
                    raw.commit()
                cursor.close()
        finally:
            raw.close()
        _SCHEMA_READY = True


@contextlib.contextmanager
def transaction(
    settings: NotificationCoreSettings | None = None,
) -> Iterator[Connection]:
    resolved = settings or load_settings()
    ensure_schema(resolved)
    with engine(resolved).begin() as connection:
        connection.execute(text(f"SET LOCAL search_path TO {qualified_schema(resolved)}, public"))
        yield connection


def database_health(settings: NotificationCoreSettings | None = None) -> dict[str, Any]:
    resolved = settings or load_settings()
    try:
        with transaction(resolved) as connection:
            row = connection.execute(
                text(
                    "SELECT revision, ready, source_count, synced_at, last_error "
                    "FROM subscription_snapshot_state WHERE singleton = TRUE"
                )
            ).mappings().one()
        return {
            "ok": True,
            "subscriptionSnapshot": {
                "revision": row["revision"],
                "ready": bool(row["ready"]),
                "sourceCount": int(row["source_count"] or 0),
                "syncedAt": row["synced_at"].isoformat() if row["synced_at"] else None,
                "lastError": bool(row["last_error"]),
            },
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}


def reset_database_state_for_tests() -> None:
    global _ENGINE, _SCHEMA_READY
    if _ENGINE is not None:
        _ENGINE.dispose()
    _ENGINE = None
    _SCHEMA_READY = False
