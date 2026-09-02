from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import TestCase


class WebappCurrentObservationMigrationTest(TestCase):
    def setUp(self) -> None:
        self.database = sqlite3.connect(":memory:")
        migration = (
            Path(__file__).parents[1]
            / "webapp"
            / "migrations"
            / "0017_add_current_observation_snapshots.sql"
        ).read_text(encoding="utf-8")
        self.database.executescript(migration)

    def tearDown(self) -> None:
        self.database.close()

    def test_migration_creates_one_bounded_snapshot_table_and_venue_index(self) -> None:
        objects = {
            (row[0], row[1])
            for row in self.database.execute(
                """
                SELECT name, type
                  FROM sqlite_master
                 WHERE name IN (
                   'current_observation_snapshots',
                   'current_observation_snapshots_venue_idx'
                 )
                """
            )
        }
        self.assertEqual(
            objects,
            {
                ("current_observation_snapshots", "table"),
                ("current_observation_snapshots_venue_idx", "index"),
            },
        )

    def test_snapshot_key_replaces_state_without_growing_history(self) -> None:
        statement = """
            INSERT INTO current_observation_snapshots (
                observation_key,
                venue_id,
                venue_name,
                healthy,
                checked_at,
                error,
                slots_json,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(observation_key) DO UPDATE SET
                healthy = excluded.healthy,
                checked_at = excluded.checked_at,
                slots_json = excluded.slots_json,
                updated_at = excluded.updated_at
        """
        self.database.execute(
            statement,
            (
                "v3:szw:day-0",
                "szw",
                "深圳湾",
                1,
                "2026-09-02T09:00:00.000Z",
                None,
                "[]",
                "2026-09-02T09:00:00.000Z",
            ),
        )
        self.database.execute(
            statement,
            (
                "v3:szw:day-0",
                "szw",
                "深圳湾",
                1,
                "2026-09-02T09:01:00.000Z",
                None,
                '[{"date":"2026-09-03"}]',
                "2026-09-02T09:01:00.000Z",
            ),
        )

        row = self.database.execute(
            """
            SELECT COUNT(*), checked_at, slots_json
              FROM current_observation_snapshots
             WHERE observation_key = 'v3:szw:day-0'
            """
        ).fetchone()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "2026-09-02T09:01:00.000Z")
        self.assertIn("2026-09-03", row[2])
