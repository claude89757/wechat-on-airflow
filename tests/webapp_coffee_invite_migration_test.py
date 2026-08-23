from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import TestCase
from uuid import uuid4


class WebappCoffeeInviteMigrationTest(TestCase):
    """Validate the server-timed, one-per-email coffee invite contract."""

    def setUp(self) -> None:
        self.database = sqlite3.connect(":memory:")
        migrations = Path(__file__).parents[1] / "webapp" / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            self.database.executescript(migration.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.database.close()

    def _create_session(
        self,
        *,
        email: str,
        shown_at: int,
        session_id: str | None = None,
        ip_hash: str = "ip-hash",
    ) -> str:
        session_id = session_id or str(uuid4())
        self.database.execute(
            """
            INSERT INTO coffee_invite_sessions
                (id, email, ip_hash, shown_at, claimable_at, expires_at,
                 consumed_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                session_id,
                email,
                ip_hash,
                shown_at,
                shown_at + 5_000,
                shown_at + 600_000,
                shown_at,
            ),
        )
        return session_id

    def _claim(
        self,
        *,
        email: str,
        session_id: str,
        now: int,
        invite_id: str | None = None,
        ip_hash: str = "ip-hash",
    ) -> tuple[int, int, int]:
        invite_id = invite_id or str(uuid4())
        expires_at = now + 30 * 86_400_000
        with self.database:
            invite = self.database.execute(
                """
                INSERT INTO priority_invite_codes
                    (id, code_hash, expires_at, active, note, created_at,
                     encrypted_code, encryption_iv, code_hint, updated_at, deleted_at)
                SELECT ?, ?, ?, 1, 'coffee_reward', ?, 'ciphertext', 'iv',
                       'ACE-SUNNY-PANDA', ?, NULL
                 WHERE EXISTS (
                   SELECT 1 FROM coffee_invite_sessions sessions
                    WHERE sessions.id = ?
                      AND sessions.email = ?
                      AND sessions.consumed_at IS NULL
                      AND sessions.claimable_at <= ?
                      AND sessions.expires_at > ?
                 )
                   AND NOT EXISTS (
                     SELECT 1 FROM coffee_invite_claims claims
                      WHERE claims.email = ?
                   )
                   AND (
                     SELECT COUNT(*) FROM coffee_invite_claims claims
                      WHERE claims.ip_hash = ? AND claims.claimed_at >= ?
                   ) < 3
                """,
                (
                    invite_id,
                    invite_id.replace("-", ""),
                    expires_at,
                    now,
                    now,
                    session_id,
                    email,
                    now,
                    now,
                    email,
                    ip_hash,
                    now - 30 * 86_400_000,
                ),
            )
            claim = self.database.execute(
                """
                INSERT INTO coffee_invite_claims
                    (email, session_id, invite_id, ip_hash, claimed_at)
                SELECT ?, ?, ?, ?, ?
                 WHERE EXISTS (
                   SELECT 1 FROM priority_invite_codes WHERE id = ?
                 )
                ON CONFLICT(email) DO NOTHING
                """,
                (email, session_id, invite_id, ip_hash, now, invite_id),
            )
            consume = self.database.execute(
                """
                UPDATE coffee_invite_sessions
                   SET consumed_at = ?
                 WHERE id = ?
                   AND email = ?
                   AND consumed_at IS NULL
                   AND EXISTS (
                     SELECT 1 FROM coffee_invite_claims claims
                      WHERE claims.email = ?
                        AND claims.session_id = ?
                        AND claims.invite_id = ?
                   )
                """,
                (now, session_id, email, email, session_id, invite_id),
            )
        return invite.rowcount, claim.rowcount, consume.rowcount

    def _start_session_conditionally(
        self,
        *,
        email: str,
        ip_hash: str,
        now: int,
    ) -> int:
        session_id = str(uuid4())
        result = self.database.execute(
            """
            INSERT INTO coffee_invite_sessions
                (id, email, ip_hash, shown_at, claimable_at, expires_at,
                 consumed_at, created_at)
            SELECT ?, ?, ?, ?, ?, ?, NULL, ?
             WHERE (
               SELECT COUNT(*) FROM coffee_invite_sessions
                WHERE email = ? AND created_at >= ?
             ) < 5
               AND (
                 SELECT COUNT(*) FROM coffee_invite_sessions
                  WHERE ip_hash = ? AND created_at >= ?
               ) < 20
            """,
            (
                session_id,
                email,
                ip_hash,
                now,
                now + 5_000,
                now + 600_000,
                now,
                email,
                now - 3_600_000,
                ip_hash,
                now - 3_600_000,
            ),
        )
        return result.rowcount

    def test_migration_creates_session_and_claim_tables(self) -> None:
        tables = {
            row[0]
            for row in self.database.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        self.assertTrue({"coffee_invite_sessions", "coffee_invite_claims"}.issubset(tables))

    def test_session_schema_enforces_the_five_second_floor(self) -> None:
        shown_at = 1_787_356_800_000
        with self.assertRaises(sqlite3.IntegrityError):
            self.database.execute(
                """
                INSERT INTO coffee_invite_sessions
                    (id, email, ip_hash, shown_at, claimable_at, expires_at,
                     consumed_at, created_at)
                VALUES (?, 'early@example.com', 'ip', ?, ?, ?, NULL, ?)
                """,
                (
                    str(uuid4()),
                    shown_at,
                    shown_at + 4_999,
                    shown_at + 600_000,
                    shown_at,
                ),
            )

    def test_session_insert_enforces_email_and_ip_rate_limits(self) -> None:
        now = 1_787_356_800_000
        for index in range(5):
            self.assertEqual(
                self._start_session_conditionally(
                    email="rate@example.com",
                    ip_hash=f"email-ip-{index}",
                    now=now + index,
                ),
                1,
            )
        self.assertEqual(
            self._start_session_conditionally(
                email="rate@example.com",
                ip_hash="email-ip-final",
                now=now + 5,
            ),
            0,
        )

        for index in range(20):
            self.assertEqual(
                self._start_session_conditionally(
                    email=f"ip-{index}@example.com",
                    ip_hash="shared-ip",
                    now=now + 100 + index,
                ),
                1,
            )
        self.assertEqual(
            self._start_session_conditionally(
                email="ip-final@example.com",
                ip_hash="shared-ip",
                now=now + 120,
            ),
            0,
        )

    def test_claim_opens_at_five_seconds_and_is_one_per_email(self) -> None:
        shown_at = 1_787_356_800_000
        email = "coffee@example.com"
        session_id = self._create_session(email=email, shown_at=shown_at)

        self.assertEqual(
            self._claim(email=email, session_id=session_id, now=shown_at + 4_999),
            (0, 0, 0),
        )
        claimed_at = shown_at + 5_000
        self.assertEqual(
            self._claim(email=email, session_id=session_id, now=claimed_at),
            (1, 1, 1),
        )
        self.assertEqual(
            self._claim(email=email, session_id=session_id, now=claimed_at + 1),
            (0, 0, 0),
        )

        second_session = self._create_session(email=email, shown_at=claimed_at + 10_000)
        self.assertEqual(
            self._claim(
                email=email,
                session_id=second_session,
                now=claimed_at + 15_000,
            ),
            (0, 0, 0),
        )
        self.assertEqual(
            self.database.execute("SELECT COUNT(*) FROM coffee_invite_claims").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.database.execute(
                "SELECT expires_at FROM priority_invite_codes WHERE note = 'coffee_reward'"
            ).fetchone()[0],
            claimed_at + 30 * 86_400_000,
        )

    def test_expired_session_cannot_create_an_invite(self) -> None:
        shown_at = 1_787_356_800_000
        email = "late@example.com"
        session_id = self._create_session(email=email, shown_at=shown_at)
        self.assertEqual(
            self._claim(email=email, session_id=session_id, now=shown_at + 600_000),
            (0, 0, 0),
        )
