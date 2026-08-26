from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import TestCase


class WebappCloudflareQuotaMigrationTest(TestCase):
    """Validate the D1 state used to suppress unchanged observations."""

    def setUp(self) -> None:
        self.database = sqlite3.connect(":memory:")
        self.database.executescript(
            """
            CREATE TABLE email_delivery_claims (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                delivery_day TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('reserved', 'sent', 'released')),
                message_id TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """
        )
        migration = (
            Path(__file__).parents[1]
            / "webapp"
            / "migrations"
            / "0009_reduce_cloudflare_free_tier_usage.sql"
        ).read_text(encoding="utf-8")
        self.database.executescript(migration)

    def tearDown(self) -> None:
        self.database.close()

    def test_migration_creates_observation_state_and_delivery_day_index(self) -> None:
        tables = {
            row[0]
            for row in self.database.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        indexes = {
            row[0]
            for row in self.database.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index'"
            )
        }
        self.assertIn("observation_ingest_state", tables)
        self.assertIn("email_delivery_claims_day_status_idx", indexes)

    def test_observation_state_upsert_replaces_only_the_latest_snapshot(self) -> None:
        self.database.execute(
            """
            INSERT INTO observation_ingest_state
                (observation_key, fingerprint, last_forwarded_at)
            VALUES ('v1:szw:empty', 'old', 100)
            ON CONFLICT(observation_key) DO UPDATE SET
                fingerprint = excluded.fingerprint,
                last_forwarded_at = excluded.last_forwarded_at
            """
        )
        self.database.execute(
            """
            INSERT INTO observation_ingest_state
                (observation_key, fingerprint, last_forwarded_at)
            VALUES ('v1:szw:empty', 'new', 200)
            ON CONFLICT(observation_key) DO UPDATE SET
                fingerprint = excluded.fingerprint,
                last_forwarded_at = excluded.last_forwarded_at
            """
        )
        self.assertEqual(
            self.database.execute(
                """
                SELECT fingerprint, last_forwarded_at
                  FROM observation_ingest_state
                 WHERE observation_key = 'v1:szw:empty'
                """
            ).fetchone(),
            ("new", 200),
        )
