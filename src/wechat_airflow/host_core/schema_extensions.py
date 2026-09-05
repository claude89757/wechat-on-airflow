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
    """
    ALTER TABLE zacks.system_email_outbox
        ADD COLUMN IF NOT EXISTS provider_error text
    """,
    """
    ALTER TABLE zacks.system_email_outbox
        ADD COLUMN IF NOT EXISTS expires_at timestamptz
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.runtime_control (
        singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
        delivery_enabled boolean NOT NULL DEFAULT false,
        activated_at timestamptz,
        deployment_commit text NOT NULL DEFAULT 'unknown',
        phase text NOT NULL DEFAULT 'prepared',
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    INSERT INTO zacks.runtime_control(singleton) VALUES (true)
        ON CONFLICT (singleton) DO NOTHING
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.current_availability (
        observation_key text NOT NULL,
        event_key text NOT NULL REFERENCES zacks.observed_slots(event_key),
        last_seen_at timestamptz NOT NULL,
        PRIMARY KEY (observation_key, event_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS current_availability_event_idx
        ON zacks.current_availability(event_key, last_seen_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.delivery_attempts (
        id text PRIMARY KEY,
        channel text NOT NULL,
        queue_ids jsonb NOT NULL,
        phase text NOT NULL,
        provider_message_id text,
        error_code text,
        started_at timestamptz NOT NULL DEFAULT now(),
        finished_at timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.wechat_outbox (
        id text PRIMARY KEY,
        venue_id text NOT NULL,
        receiver text NOT NULL,
        device_name text NOT NULL,
        source text NOT NULL,
        message text NOT NULL,
        event_keys jsonb NOT NULL,
        status text NOT NULL DEFAULT 'pending',
        attempt_count integer NOT NULL DEFAULT 0,
        next_attempt_at timestamptz NOT NULL DEFAULT now(),
        expires_at timestamptz NOT NULL,
        lease_owner text,
        lease_until timestamptz,
        outbound_message text,
        program_id text,
        sent_at timestamptz,
        last_error text,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS wechat_outbox_due_idx
        ON zacks.wechat_outbox(status, next_attempt_at, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.booking_link_cooldowns (
        receiver_hash text NOT NULL,
        program_id text NOT NULL,
        sent_at timestamptz NOT NULL,
        PRIMARY KEY(receiver_hash, program_id)
    )
    """,
    """
    ALTER TABLE zacks.notification_outbox
        ADD COLUMN IF NOT EXISTS delivery_claim_id text
    """,
    "ALTER TABLE zacks.runtime_control ADD COLUMN IF NOT EXISTS deployment_started_at timestamptz NOT NULL DEFAULT now()",
    "ALTER TABLE zacks.observation_state ADD COLUMN IF NOT EXISTS healthy boolean NOT NULL DEFAULT false",
    "ALTER TABLE zacks.runtime_control ADD COLUMN IF NOT EXISTS acceptance_started_at timestamptz",
    "ALTER TABLE zacks.runtime_control ADD COLUMN IF NOT EXISTS wechat_enabled boolean NOT NULL DEFAULT false",
    "ALTER TABLE zacks.runtime_control ADD COLUMN IF NOT EXISTS api_acceptance jsonb",
)
