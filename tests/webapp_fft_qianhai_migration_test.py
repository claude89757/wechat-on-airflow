from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import TestCase


class WebappFftQianhaiMigrationTest(TestCase):
    def test_migration_registers_fft_qianhai_once(self) -> None:
        database = sqlite3.connect(":memory:")
        try:
            database.executescript(
                """
                CREATE TABLE venue_status (
                    venue_id TEXT PRIMARY KEY,
                    venue_name TEXT NOT NULL,
                    healthy INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                """
            )
            migration = (
                Path(__file__).parents[1]
                / "webapp"
                / "migrations"
                / "0014_add_fft_qianhai_venue.sql"
            ).read_text(encoding="utf-8")
            database.executescript(migration)
            database.executescript(migration)
            self.assertEqual(
                database.execute(
                    "SELECT venue_id, venue_name, healthy FROM venue_status"
                ).fetchall(),
                [("fft_qianhai", "FFTENNIS前海国际网球中心", 0)],
            )
        finally:
            database.close()
