from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import TestCase
from uuid import uuid4


class WebappDeliveryTiersMigrationTest(TestCase):
    """Validate D1 schema and quota SQL against SQLite semantics."""

    def setUp(self) -> None:
        self.database = sqlite3.connect(":memory:")
        self.database.executescript(
            """
            CREATE TABLE notification_outbox (
                id TEXT PRIMARY KEY,
                subscription_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                venue_id TEXT NOT NULL,
                email TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                next_attempt_at INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                sent_at TEXT,
                message_id TEXT,
                last_error TEXT,
                UNIQUE (subscription_id, event_key)
            );
            """
        )
        migration = (
            Path(__file__).parents[1]
            / "webapp"
            / "migrations"
            / "0004_add_delivery_tiers_and_invites.sql"
        ).read_text(encoding="utf-8")
        self.database.executescript(migration)

    def tearDown(self) -> None:
        self.database.close()

    def test_migration_creates_tier_invite_and_delivery_claim_tables(self) -> None:
        tables = {
            row[0]
            for row in self.database.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        self.assertTrue(
            {
                "user_delivery_tiers",
                "priority_invite_codes",
                "priority_invite_attempts",
                "email_delivery_claims",
            }.issubset(tables)
        )

    def test_invite_claim_and_tier_assignment_are_one_time(self) -> None:
        now = 1_787_356_800_000
        email = "user@example.com"
        invite_id = str(uuid4())
        code_hash = "a" * 64
        self.database.execute(
            """
            INSERT INTO priority_invite_codes
                (id, code_hash, expires_at, active, created_at)
            VALUES (?, ?, ?, 1, ?)
            """,
            (invite_id, code_hash, now + 86_400_000, now),
        )

        redemption_id = str(uuid4())
        with self.database:
            claimed = self.database.execute(
                """
                UPDATE priority_invite_codes
                   SET redeemed_by = ?, redeemed_at = ?, redemption_id = ?
                 WHERE code_hash = ?
                   AND active = 1
                   AND redeemed_by IS NULL
                   AND expires_at > ?
                """,
                (email, now, redemption_id, code_hash, now),
            )
            assigned = self.database.execute(
                """
                INSERT INTO user_delivery_tiers
                    (email, tier, source_invite_id, created_at, updated_at, revoked_at)
                SELECT ?, 'priority', id, ?, ?, NULL
                  FROM priority_invite_codes
                 WHERE redemption_id = ?
                   AND redeemed_by = ?
                ON CONFLICT(email) DO UPDATE SET
                    tier = 'priority',
                    source_invite_id = excluded.source_invite_id,
                    updated_at = excluded.updated_at,
                    revoked_at = NULL
                """,
                (email, now, now, redemption_id, email),
            )

        self.assertEqual(claimed.rowcount, 1)
        self.assertEqual(assigned.rowcount, 1)
        self.assertEqual(
            self.database.execute(
                "SELECT tier, source_invite_id FROM user_delivery_tiers WHERE email = ?",
                (email,),
            ).fetchone(),
            ("priority", invite_id),
        )
        second_claim = self.database.execute(
            """
            UPDATE priority_invite_codes
               SET redeemed_by = ?, redeemed_at = ?, redemption_id = ?
             WHERE code_hash = ?
               AND active = 1
               AND redeemed_by IS NULL
               AND expires_at > ?
            """,
            ("other@example.com", now, str(uuid4()), code_hash, now),
        )
        self.assertEqual(second_claim.rowcount, 0)

    def test_delivery_reservation_closes_exactly_at_daily_limit(self) -> None:
        now = 1_787_356_800_000
        day_start = "2026-08-21T16:00:00.000Z"
        delivery_day = "2026-08-22"
        email = "user@example.com"
        daily_limit = 10
        for index in range(daily_limit - 1):
            self.database.execute(
                """
                INSERT INTO notification_outbox
                    (id, subscription_id, event_key, venue_id, email, subject, body,
                     status, attempt_count, next_attempt_at, created_at, sent_at, message_id)
                VALUES (?, ?, ?, 'szw', ?, 'subject', 'body',
                        'sent', 1, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    str(uuid4()),
                    str(uuid4()),
                    email,
                    now,
                    "2026-08-22T01:00:00.000Z",
                    "2026-08-22T01:00:00.000Z",
                    f"message-{index}",
                ),
            )

        def reserve() -> int:
            result = self.database.execute(
                """
                INSERT INTO email_delivery_claims
                    (id, email, delivery_day, status, message_id, created_at, updated_at)
                SELECT ?, ?, ?, 'reserved', NULL, ?, ?
                 WHERE (
                    SELECT COUNT(DISTINCT message_id)
                      FROM notification_outbox
                     WHERE email = ?
                       AND status = 'sent'
                       AND sent_at >= ?
                 ) + (
                    SELECT COUNT(*)
                      FROM email_delivery_claims
                     WHERE email = ?
                       AND delivery_day = ?
                       AND status = 'reserved'
                       AND updated_at >= ?
                 ) < ?
                """,
                (
                    str(uuid4()),
                    email,
                    delivery_day,
                    now,
                    now,
                    email,
                    day_start,
                    email,
                    delivery_day,
                    now - 600_000,
                    daily_limit,
                ),
            )
            return result.rowcount

        self.assertEqual(reserve(), 1)
        self.assertEqual(reserve(), 0)
