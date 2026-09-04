from __future__ import annotations

import gzip
from pathlib import Path

from scripts.import_d1_sql_export import sha256_file, snapshot_from_sql_export

SQL = """
PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE subscriptions (id TEXT PRIMARY KEY, email TEXT, active INTEGER);
CREATE TABLE venue_status (venue_id TEXT PRIMARY KEY, healthy INTEGER);
CREATE TABLE notification_outbox (id TEXT PRIMARY KEY, status TEXT);
CREATE TABLE user_profiles (email TEXT PRIMARY KEY, display_name TEXT);
INSERT INTO subscriptions VALUES ('s1', 'masked@example.test', 1);
INSERT INTO venue_status VALUES ('szw', 1);
INSERT INTO notification_outbox VALUES ('n1', 'delivered');
INSERT INTO user_profiles VALUES ('masked@example.test', 'Masked');
COMMIT;
""".strip()


def test_plain_d1_sql_export_is_loaded_into_fixed_snapshot_tables(tmp_path: Path) -> None:
    export = tmp_path / "d1.sql"
    export.write_text(SQL, encoding="utf-8")

    snapshot = snapshot_from_sql_export(export)

    assert snapshot["subscriptions"] == [{"id": "s1", "email": "masked@example.test", "active": 1}]
    assert snapshot["venue_status"] == [{"venue_id": "szw", "healthy": 1}]
    assert snapshot["notification_outbox"] == [{"id": "n1", "status": "delivered"}]
    assert snapshot["user_profiles"][0]["display_name"] == "Masked"
    assert snapshot["user_roles"] == []


def test_gzipped_d1_sql_export_and_checksum_are_supported(tmp_path: Path) -> None:
    export = tmp_path / "d1.sql.gz"
    with gzip.open(export, "wt", encoding="utf-8") as handle:
        handle.write(SQL)

    snapshot = snapshot_from_sql_export(export)

    assert len(sha256_file(export)) == 64
    assert snapshot["subscriptions"][0]["id"] == "s1"
