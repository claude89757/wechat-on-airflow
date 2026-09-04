#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from wechat_airflow.host_core.migration import EXPORT_TABLES, import_snapshot

REQUIRED_TABLES = {"subscriptions", "venue_status", "notification_outbox"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_sql(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return handle.read()
    return path.read_text(encoding="utf-8")


def snapshot_from_sql_export(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.is_file():
        raise RuntimeError(f"D1 SQL export does not exist: {path}")
    sql = read_sql(path)
    if not sql.strip():
        raise RuntimeError("D1 SQL export is empty")

    descriptor, database_name = tempfile.mkstemp(prefix="zacks-d1-export-", suffix=".sqlite3")
    os.close(descriptor)
    database_path = Path(database_name)
    try:
        connection = sqlite3.connect(str(database_path))
        connection.row_factory = sqlite3.Row
        try:
            connection.executescript(sql)
            existing = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            missing_required = sorted(REQUIRED_TABLES - existing)
            if missing_required:
                raise RuntimeError(
                    "D1 SQL export is missing required tables: " + ", ".join(missing_required)
                )

            snapshot: dict[str, list[dict[str, Any]]] = {}
            for table in EXPORT_TABLES:
                if table not in existing:
                    snapshot[table] = []
                    continue
                quoted = '"' + table.replace('"', '""') + '"'
                rows = connection.execute(f"SELECT * FROM {quoted}").fetchall()
                snapshot[table] = [dict(row) for row in rows]
            return snapshot
        finally:
            connection.close()
    finally:
        try:
            database_path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import a Cloudflare D1 control-plane SQL export into host PostgreSQL"
    )
    parser.add_argument("--sql-export", required=True, type=Path)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--snapshot-only", action="store_true")
    arguments = parser.parse_args()

    actual_sha256 = sha256_file(arguments.sql_export)
    if arguments.expected_sha256 and actual_sha256 != arguments.expected_sha256.lower():
        raise RuntimeError(
            f"D1 SQL export checksum mismatch: expected {arguments.expected_sha256}, "
            f"got {actual_sha256}"
        )

    snapshot = snapshot_from_sql_export(arguments.sql_export)
    counts = {table: len(snapshot.get(table, [])) for table in EXPORT_TABLES}
    payload: dict[str, Any] = {
        "success": True,
        "sha256": actual_sha256,
        "counts": counts,
    }
    if not arguments.snapshot_only:
        payload["imported"] = import_snapshot(
            snapshot,
            source_revision=arguments.source_revision,
        )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
