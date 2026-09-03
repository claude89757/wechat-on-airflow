from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_subscription_event_snapshot_query_is_indexed() -> None:
    database = sqlite3.connect(":memory:")
    database.executescript(
        """
        CREATE TABLE subscription_events (
            subscription_id TEXT NOT NULL,
            event_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (subscription_id, event_key)
        );
        """
    )
    database.executescript(
        (ROOT / "webapp/migrations/0017_add_subscription_event_snapshot_index.sql").read_text(
            encoding="utf-8"
        )
    )
    plan = database.execute(
        """
        EXPLAIN QUERY PLAN
        SELECT subscription_id, event_key, created_at
          FROM subscription_events
         WHERE created_at >= ?
         ORDER BY created_at, subscription_id, event_key
         LIMIT 100000
        """,
        ("2026-08-01T00:00:00Z",),
    ).fetchall()
    detail = "\n".join(str(row[-1]) for row in plan)
    assert "subscription_events_created_snapshot_idx" in detail
    assert "USE TEMP B-TREE" not in detail
