from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import text

from .database import transaction

DELIVERY_LOCK = 728190315


def runtime_state() -> dict[str, Any]:
    with transaction() as connection:
        return dict(
            connection.execute(text("SELECT * FROM zacks.runtime_control WHERE singleton = true"))
            .mappings()
            .one()
        )


def set_delivery_enabled(enabled: bool, commit: str) -> None:
    """Fence delivery changes against in-flight sends, never reactivate D1."""
    with transaction() as connection:
        connection.execute(text("SET LOCAL lock_timeout = '300s'"))
        connection.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": DELIVERY_LOCK})
        if enabled:
            rows = (
                connection.execute(
                    text(
                        "SELECT details FROM zacks.migration_state WHERE source='cloudflare-d1' AND imported_at IS NOT NULL"
                    )
                )
                .mappings()
                .all()
            )
            from .migration import EXPORT_TABLES

            proof = rows[0]["details"].get("reconciliation", {}) if rows else {}
            verified = proof.get("providerIdentityPreserved") is True and all(
                isinstance(proof.get(table), dict)
                and isinstance(proof[table].get("sourceCount"), int)
                and proof[table]["sourceCount"] == proof[table].get("matchedCount")
                and len(str(proof[table].get("keysSha256", ""))) == 64
                for table in EXPORT_TABLES
            )
            if not verified:
                raise RuntimeError("Host delivery requires a verified migration checkpoint")
        connection.execute(
            text("""
            UPDATE zacks.runtime_control
            SET delivery_enabled = :enabled,
                activated_at = CASE WHEN :enabled THEN COALESCE(activated_at, now()) ELSE activated_at END,
                deployment_commit = :commit,
                phase = CASE WHEN :enabled THEN 'active' ELSE 'paused' END,
                updated_at = now()
            WHERE singleton = true
        """),
            {"enabled": enabled, "commit": commit},
        )


@contextmanager
def delivery_guard() -> Iterator[bool]:
    """A shared transaction fence makes pause wait for bounded in-flight I/O."""
    with transaction() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": DELIVERY_LOCK}
        )
        enabled = connection.execute(
            text("SELECT delivery_enabled FROM zacks.runtime_control WHERE singleton = true")
        ).scalar_one()
        yield bool(enabled)
