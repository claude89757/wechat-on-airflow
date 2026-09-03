from __future__ import annotations

# Additive statements are kept separate from the initial schema so a rolling
# release can safely upgrade a host that already bootstrapped host-core v1.
SCHEMA_EXTENSION_STATEMENTS: tuple[str, ...] = (
    """
    ALTER TABLE zacks.notification_outbox
        ADD COLUMN IF NOT EXISTS provider_check_count integer NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE zacks.notification_outbox
        ADD COLUMN IF NOT EXISTS provider_next_check_at timestamptz
    """,
    """
    CREATE INDEX IF NOT EXISTS notification_outbox_provider_due_idx
        ON zacks.notification_outbox(provider_next_check_at, submitted_at, message_id)
        WHERE status = 'submitted' AND message_id IS NOT NULL
    """,
    """
    ALTER TABLE zacks.system_email_outbox
        ADD COLUMN IF NOT EXISTS provider_check_count integer NOT NULL DEFAULT 0
    """,
    """
    ALTER TABLE zacks.system_email_outbox
        ADD COLUMN IF NOT EXISTS provider_next_check_at timestamptz
    """,
    """
    CREATE INDEX IF NOT EXISTS system_email_outbox_provider_due_idx
        ON zacks.system_email_outbox(provider_next_check_at, submitted_at, provider_message_id)
        WHERE status = 'submitted' AND provider_message_id IS NOT NULL
    """,
)
