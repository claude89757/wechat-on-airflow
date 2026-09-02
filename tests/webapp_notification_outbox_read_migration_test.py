from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import TestCase


class WebappNotificationOutboxReadMigrationTest(TestCase):
    """Keep the production D1 hot paths on bounded index scans."""

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
                provider_request_id TEXT,
                provider_status TEXT,
                provider_submitted_at TEXT,
                provider_delivered_at TEXT,
                provider_failed_at TEXT,
                provider_checked_at INTEGER,
                provider_error TEXT,
                UNIQUE (subscription_id, event_key)
            );

            CREATE INDEX notification_outbox_pending_idx
                ON notification_outbox(status, next_attempt_at);
            CREATE INDEX notification_outbox_sent_idx
                ON notification_outbox(sent_at);
            CREATE INDEX notification_outbox_provider_status_idx
                ON notification_outbox(
                    status,
                    provider_checked_at,
                    provider_submitted_at
                );
            """
        )
        rows = []
        for index in range(2_000):
            day = 1 + index // 100
            submitted_at = f"2026-08-{day:02d}T00:{index % 60:02d}:00.000Z"
            status = "delivered" if index % 3 else "submitted"
            delivered_at = submitted_at if status == "delivered" else None
            rows.append(
                (
                    f"id-{index}",
                    f"subscription-{index}",
                    f"event-{index}",
                    f"venue-{index % 10}",
                    f"user-{index % 20}@example.com",
                    "subject",
                    "body",
                    status,
                    submitted_at,
                    f"message-{index // 2}",
                    submitted_at,
                    delivered_at,
                    index,
                )
            )
        self.database.executemany(
            """
            INSERT INTO notification_outbox (
                id,
                subscription_id,
                event_key,
                venue_id,
                email,
                subject,
                body,
                status,
                next_attempt_at,
                created_at,
                message_id,
                provider_submitted_at,
                provider_delivered_at,
                provider_checked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        migration = (
            Path(__file__).parents[1]
            / "webapp"
            / "migrations"
            / "0016_optimize_notification_outbox_reads.sql"
        ).read_text(encoding="utf-8")
        self.database.executescript(migration)

    def tearDown(self) -> None:
        self.database.close()

    def query_plan(self, sql: str, parameters: tuple[object, ...]) -> str:
        return " | ".join(
            str(row[3])
            for row in self.database.execute(
                f"EXPLAIN QUERY PLAN {sql}",
                parameters,
            )
        )

    def test_migration_creates_targeted_partial_indexes(self) -> None:
        indexes = {
            row[0]: row[1]
            for row in self.database.execute(
                """
                SELECT name, sql
                  FROM sqlite_master
                 WHERE type = 'index'
                   AND name LIKE 'notification_outbox_%_lookup_idx'
                """
            )
        }
        self.assertEqual(
            set(indexes),
            {
                "notification_outbox_message_id_lookup_idx",
                "notification_outbox_submitted_at_lookup_idx",
                "notification_outbox_delivered_at_lookup_idx",
            },
        )
        self.assertTrue(
            all(
                " WHERE " in str(definition).upper()
                for definition in indexes.values()
            )
        )

    def test_daily_and_message_queries_use_bounded_indexes(self) -> None:
        submitted_plan = self.query_plan(
            """
            SELECT COUNT(DISTINCT message_id)
              FROM notification_outbox
             WHERE provider_submitted_at >= ?
            """,
            ("2026-08-18T00:00:00.000Z",),
        )
        recipient_plan = self.query_plan(
            """
            SELECT COUNT(DISTINCT message_id)
              FROM notification_outbox
             WHERE email = ?
               AND provider_submitted_at >= ?
            """,
            ("user-1@example.com", "2026-08-18T00:00:00.000Z"),
        )
        delivered_plan = self.query_plan(
            """
            SELECT COUNT(DISTINCT message_id)
              FROM notification_outbox
             WHERE status = 'delivered'
               AND provider_delivered_at >= ?
            """,
            ("2026-08-18T00:00:00.000Z",),
        )
        message_plan = self.query_plan(
            """
            SELECT DISTINCT venue_id
              FROM notification_outbox
             WHERE message_id = ?
            """,
            ("message-100",),
        )

        self.assertIn(
            "notification_outbox_submitted_at_lookup_idx",
            submitted_plan,
        )
        self.assertIn(
            "notification_outbox_submitted_at_lookup_idx",
            recipient_plan,
        )
        self.assertIn(
            "notification_outbox_delivered_at_lookup_idx",
            delivered_plan,
        )
        self.assertIn(
            "notification_outbox_message_id_lookup_idx",
            message_plan,
        )
        for plan in (submitted_plan, recipient_plan, delivered_plan, message_plan):
            self.assertNotIn("SCAN notification_outbox", plan)
