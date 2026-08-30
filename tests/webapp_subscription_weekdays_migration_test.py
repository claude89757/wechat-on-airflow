from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import TestCase


class WebappSubscriptionWeekdaysMigrationTest(TestCase):
    """Keep existing subscriptions active every day while adding weekday filters."""

    def setUp(self) -> None:
        self.database = sqlite3.connect(":memory:")
        self.database.executescript(
            """
            CREATE TABLE subscriptions (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL
            );
            INSERT INTO subscriptions (id, email)
            VALUES ('legacy', 'legacy@example.com');
            """
        )
        migration = (
            Path(__file__).parents[1]
            / "webapp"
            / "migrations"
            / "0013_add_subscription_weekdays.sql"
        ).read_text(encoding="utf-8")
        self.database.executescript(migration)

    def tearDown(self) -> None:
        self.database.close()

    def test_existing_rows_default_to_all_seven_days(self) -> None:
        self.assertEqual(
            self.database.execute(
                "SELECT weekday_mask FROM subscriptions WHERE id = 'legacy'"
            ).fetchone(),
            (127,),
        )

    def test_weekend_mask_is_persisted_and_invalid_masks_are_rejected(self) -> None:
        self.database.execute(
            "INSERT INTO subscriptions (id, email, weekday_mask) VALUES (?, ?, ?)",
            ("weekend", "weekend@example.com", 96),
        )
        self.assertEqual(
            self.database.execute(
                "SELECT weekday_mask FROM subscriptions WHERE id = 'weekend'"
            ).fetchone(),
            (96,),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.execute(
                "INSERT INTO subscriptions (id, email, weekday_mask) VALUES (?, ?, ?)",
                ("invalid", "invalid@example.com", 0),
            )
