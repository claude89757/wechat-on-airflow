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


def claim(key: str, payload_hash: str, *, preparing: bool = False) -> tuple[str, dict | None]:
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
                elif preparing and row[1] in {"preparing", "not_submitted"}:
                    database.execute(
                        "UPDATE sends SET status='preparing', result_json=NULL, updated_at=CURRENT_TIMESTAMP WHERE idempotency_key=?",
                        (key,),
                    )
                    result = ("claimed", None)
                else:
                    result = ("submission_unknown", None)
            else:
                database.execute(
                    "INSERT INTO sends(idempotency_key,payload_hash,status) VALUES(?,?,?)",
                    (key, payload_hash, "preparing" if preparing else "dispatching"),
                )
                result = ("claimed", None)
            database.execute("COMMIT")
            return result
        except BaseException:
            database.execute("ROLLBACK")
            raise


def mark_submitting(key: str) -> None:
    """Durably cross the irreversible boundary BEFORE the first UI send action."""
    with connection() as database:
        changed = database.execute(
            "UPDATE sends SET status='dispatching', updated_at=CURRENT_TIMESTAMP "
            "WHERE idempotency_key=? AND status='preparing'",
            (key,),
        ).rowcount
        if changed != 1:
            raise RuntimeError("sender checkpoint was not acknowledged")


def finish(key: str, status: str, result: dict | None = None) -> None:
    if status not in {"sent", "submission_unknown", "not_submitted"}:
        raise ValueError("invalid sender ledger result")
    with connection() as database:
        database.execute(
            "UPDATE sends SET status=?, result_json=?, updated_at=CURRENT_TIMESTAMP "
            "WHERE idempotency_key=? AND status IN ('preparing','dispatching') "
            "AND (? != 'not_submitted' OR status='preparing')",
            (status, json.dumps(result, ensure_ascii=False) if result else None, key, status),
        )


def ready() -> bool:
    try:
        with connection() as database:
            return database.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    except (OSError, RuntimeError, sqlite3.Error):
        return False


def lookup(key: str, payload_hash: str) -> dict:
    with connection() as database:
        row = database.execute(
            "SELECT status, result_json, updated_at FROM sends WHERE idempotency_key=? AND payload_hash=?",
            (key, payload_hash),
        ).fetchone()
    if row is None:
        return {"status": "not_found"}
    payload = json.loads(row[1]) if row[1] else {}
    return {
        "status": row[0],
        "updated_at": row[2],
        "confirmed": row[0] == "sent" and payload.get("success") is True,
        "sent_count": payload.get("sent_count", 0),
    }
