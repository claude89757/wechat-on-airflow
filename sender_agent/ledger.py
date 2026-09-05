"""Durable device-side idempotency; unknown UI outcomes are never auto-replayed."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connection():
    configured = os.environ.get("WECHAT_IDEMPOTENCY_PATH", "").strip()
    if not configured:
        raise RuntimeError("durable sender ledger is not configured")
    path = Path(configured)
    if not path.is_absolute() or not path.parent.is_dir():
        raise RuntimeError("durable sender ledger directory is unavailable")
    database = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    try:
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA synchronous=FULL")
        database.execute("""CREATE TABLE IF NOT EXISTS sends (
            idempotency_key TEXT PRIMARY KEY, payload_hash TEXT NOT NULL,
            status TEXT NOT NULL, result_json TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        os.chmod(path, 0o600)
        yield database
    finally:
        database.close()


def claim(key: str, payload_hash: str) -> tuple[str, dict | None]:
    with connection() as database:
        database.execute("BEGIN IMMEDIATE")
        try:
            row = database.execute(
                "SELECT payload_hash, status, result_json FROM sends WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
            if row:
                if row[0] != payload_hash:
                    result = ("conflict", None)
                elif row[1] == "sent":
                    result = ("sent", json.loads(row[2]))
                else:
                    result = ("submission_unknown", None)
            else:
                database.execute(
                    "INSERT INTO sends(idempotency_key,payload_hash,status) VALUES(?,?,'dispatching')",
                    (key, payload_hash),
                )
                result = ("claimed", None)
            database.execute("COMMIT")
            return result
        except BaseException:
            database.execute("ROLLBACK")
            raise


def finish(key: str, status: str, result: dict | None = None) -> None:
    if status not in {"sent", "submission_unknown"}:
        raise ValueError("invalid sender ledger result")
    with connection() as database:
        database.execute(
            "UPDATE sends SET status=?, result_json=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE idempotency_key=? AND status='dispatching'",
            (status, json.dumps(result, ensure_ascii=False) if result else None, key),
        )


def ready() -> bool:
    try:
        with connection() as database:
            return database.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    except (OSError, RuntimeError, sqlite3.Error):
        return False
