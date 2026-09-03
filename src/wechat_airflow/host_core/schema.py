from __future__ import annotations

SCHEMA_VERSION = "0.7.0-host-core-v1"

SCHEMA_STATEMENTS: tuple[str, ...] = (
    "CREATE SCHEMA IF NOT EXISTS zacks",
    """
    CREATE TABLE IF NOT EXISTS zacks.schema_versions (
        version text PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.verification_challenges (
        id text PRIMARY KEY,
        email text NOT NULL,
        code_hash text NOT NULL,
        ip_hash text NOT NULL,
        expires_at timestamptz NOT NULL,
        attempts integer NOT NULL DEFAULT 0,
        consumed_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS verification_challenges_email_created_idx
        ON zacks.verification_challenges(email, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS verification_challenges_ip_created_idx
        ON zacks.verification_challenges(ip_hash, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.verified_receipts (
        token_hash text PRIMARY KEY,
        email text NOT NULL,
        masked_email text NOT NULL,
        expires_at timestamptz NOT NULL,
        last_used_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        revoked_at timestamptz
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS verified_receipts_email_idx
        ON zacks.verified_receipts(email)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.user_profiles (
        email text PRIMARY KEY,
        masked_email text NOT NULL,
        first_verified_at timestamptz NOT NULL,
        last_verified_at timestamptz NOT NULL,
        last_login_at timestamptz NOT NULL,
        last_active_at timestamptz NOT NULL,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.user_roles (
        email text NOT NULL,
        role text NOT NULL,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        revoked_at timestamptz,
        PRIMARY KEY (email, role)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS user_roles_active_idx
        ON zacks.user_roles(role, revoked_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.user_delivery_tiers (
        email text PRIMARY KEY,
        tier text NOT NULL DEFAULT 'standard',
        source_invite_id text,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        revoked_at timestamptz
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS user_delivery_tiers_active_idx
        ON zacks.user_delivery_tiers(tier, revoked_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.priority_invite_codes (
        id text PRIMARY KEY,
        code_hash text NOT NULL UNIQUE,
        encrypted_code text,
        code_hint text,
        expires_at timestamptz NOT NULL,
        active boolean NOT NULL DEFAULT true,
        note text,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        redeemed_by text,
        redeemed_at timestamptz,
        deleted_at timestamptz
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS priority_invite_codes_available_idx
        ON zacks.priority_invite_codes(active, expires_at, redeemed_at)
        WHERE deleted_at IS NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.priority_invite_attempts (
        id text PRIMARY KEY,
        email text NOT NULL,
        ip_hash text NOT NULL,
        success boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS priority_invite_attempts_email_created_idx
        ON zacks.priority_invite_attempts(email, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS priority_invite_attempts_ip_created_idx
        ON zacks.priority_invite_attempts(ip_hash, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.coffee_invite_sessions (
        id text PRIMARY KEY,
        email text NOT NULL,
        ip_hash text NOT NULL,
        shown_at timestamptz NOT NULL,
        claimable_at timestamptz NOT NULL,
        expires_at timestamptz NOT NULL,
        consumed_at timestamptz,
        created_at timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS coffee_invite_sessions_email_created_idx
        ON zacks.coffee_invite_sessions(email, created_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS coffee_invite_sessions_ip_created_idx
        ON zacks.coffee_invite_sessions(ip_hash, created_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.coffee_invite_claims (
        email text PRIMARY KEY,
        session_id text NOT NULL,
        invite_id text NOT NULL UNIQUE,
        ip_hash text NOT NULL,
        claimed_at timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS coffee_invite_claims_ip_claimed_idx
        ON zacks.coffee_invite_claims(ip_hash, claimed_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.subscriptions (
        id text PRIMARY KEY,
        email text NOT NULL,
        venue_ids jsonb NOT NULL,
        start_time text NOT NULL,
        end_time text NOT NULL,
        weekday_mask integer NOT NULL DEFAULT 127,
        duration_days integer NOT NULL,
        term_code text NOT NULL,
        auto_renew boolean NOT NULL DEFAULT false,
        dedupe_key text,
        active_until timestamptz NOT NULL,
        active boolean NOT NULL DEFAULT true,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS subscriptions_email_idx
        ON zacks.subscriptions(email, active, active_until DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS subscriptions_active_until_idx
        ON zacks.subscriptions(active, active_until)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS subscriptions_active_dedupe_idx
        ON zacks.subscriptions(email, dedupe_key)
        WHERE active AND dedupe_key IS NOT NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.subscription_venues (
        subscription_id text NOT NULL REFERENCES zacks.subscriptions(id) ON DELETE CASCADE,
        venue_id text NOT NULL,
        PRIMARY KEY (subscription_id, venue_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS subscription_venues_venue_idx
        ON zacks.subscription_venues(venue_id, subscription_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.subscription_generations (
        venue_id text PRIMARY KEY,
        generation bigint NOT NULL DEFAULT 0,
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.venue_status (
        venue_id text PRIMARY KEY,
        venue_name text NOT NULL,
        healthy boolean NOT NULL DEFAULT false,
        last_inspection_at timestamptz,
        last_notification_at timestamptz,
        last_error text,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.observation_state (
        observation_key text PRIMARY KEY,
        venue_id text NOT NULL,
        fingerprint text NOT NULL,
        subscription_generation bigint NOT NULL DEFAULT 0,
        last_seen_at timestamptz NOT NULL,
        last_matched_at timestamptz,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS observation_state_venue_idx
        ON zacks.observation_state(venue_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.observed_slots (
        event_key text PRIMARY KEY,
        venue_id text NOT NULL,
        court_name text NOT NULL,
        booking_date date NOT NULL,
        start_time text NOT NULL,
        end_time text NOT NULL,
        first_observed_at timestamptz NOT NULL,
        last_observed_at timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS observed_slots_venue_date_idx
        ON zacks.observed_slots(venue_id, booking_date)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.subscription_events (
        subscription_id text NOT NULL,
        event_key text NOT NULL,
        created_at timestamptz NOT NULL,
        PRIMARY KEY (subscription_id, event_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.notification_outbox (
        id text PRIMARY KEY,
        subscription_id text NOT NULL,
        event_key text NOT NULL,
        venue_id text NOT NULL,
        email text NOT NULL,
        subject text NOT NULL,
        body text NOT NULL,
        tier text NOT NULL DEFAULT 'standard',
        status text NOT NULL DEFAULT 'pending',
        attempt_count integer NOT NULL DEFAULT 0,
        next_attempt_at timestamptz NOT NULL,
        lease_owner text,
        lease_until timestamptz,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL,
        submitted_at timestamptz,
        delivered_at timestamptz,
        failed_at timestamptz,
        message_id text,
        provider_request_id text,
        provider_status text,
        provider_checked_at timestamptz,
        provider_error text,
        last_error text,
        UNIQUE (subscription_id, event_key)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS notification_outbox_pending_idx
        ON zacks.notification_outbox(status, next_attempt_at, created_at)
        WHERE status IN ('pending', 'retry', 'processing')
    """,
    """
    CREATE INDEX IF NOT EXISTS notification_outbox_message_id_idx
        ON zacks.notification_outbox(message_id)
        WHERE message_id IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS notification_outbox_email_submitted_idx
        ON zacks.notification_outbox(email, submitted_at)
        WHERE submitted_at IS NOT NULL
    """,
    """
    CREATE INDEX IF NOT EXISTS notification_outbox_delivery_idx
        ON zacks.notification_outbox(status, delivered_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.system_email_outbox (
        id text PRIMARY KEY,
        dedupe_key text NOT NULL UNIQUE,
        email text NOT NULL,
        email_type text NOT NULL,
        subject text NOT NULL,
        body text NOT NULL,
        status text NOT NULL DEFAULT 'pending',
        attempt_count integer NOT NULL DEFAULT 0,
        next_attempt_at timestamptz NOT NULL,
        lease_owner text,
        lease_until timestamptz,
        provider_message_id text,
        provider_request_id text,
        provider_status text,
        submitted_at timestamptz,
        delivered_at timestamptz,
        failed_at timestamptz,
        provider_checked_at timestamptz,
        last_error text,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS system_email_outbox_pending_idx
        ON zacks.system_email_outbox(status, next_attempt_at, created_at)
        WHERE status IN ('pending', 'retry', 'processing')
    """,
    """
    CREATE INDEX IF NOT EXISTS system_email_outbox_provider_idx
        ON zacks.system_email_outbox(status, provider_checked_at, submitted_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.email_delivery_claims (
        id text PRIMARY KEY,
        email text NOT NULL,
        delivery_day date NOT NULL,
        status text NOT NULL,
        message_id text,
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS email_delivery_claims_quota_idx
        ON zacks.email_delivery_claims(email, delivery_day, status, updated_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.wechat_delivery_incidents (
        id text PRIMARY KEY,
        source text NOT NULL,
        receiver_hash text NOT NULL,
        message_hash text NOT NULL,
        error_code text,
        error_message text,
        first_failed_at timestamptz NOT NULL,
        last_failed_at timestamptz NOT NULL,
        attempt_count integer NOT NULL DEFAULT 1,
        resolved_at timestamptz,
        UNIQUE (source, receiver_hash, message_hash)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS wechat_delivery_incidents_open_idx
        ON zacks.wechat_delivery_incidents(last_failed_at DESC)
        WHERE resolved_at IS NULL
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.runtime_heartbeats (
        component text PRIMARY KEY,
        deployment_commit text NOT NULL,
        healthy boolean NOT NULL,
        details jsonb NOT NULL DEFAULT '{}'::jsonb,
        updated_at timestamptz NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS zacks.migration_state (
        source text PRIMARY KEY,
        source_revision text,
        imported_at timestamptz,
        cutover_at timestamptz,
        details jsonb NOT NULL DEFAULT '{}'::jsonb,
        updated_at timestamptz NOT NULL DEFAULT now()
    )
    """,
)
