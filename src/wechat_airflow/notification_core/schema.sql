CREATE SCHEMA IF NOT EXISTS zacks_core;
SET search_path TO zacks_core, public;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subscription_snapshot_state (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    revision TEXT NOT NULL DEFAULT 'uninitialized',
    source_generated_at TIMESTAMPTZ,
    synced_at TIMESTAMPTZ,
    ready BOOLEAN NOT NULL DEFAULT FALSE,
    source_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
INSERT INTO subscription_snapshot_state(singleton)
VALUES (TRUE)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    weekday_mask SMALLINT NOT NULL CHECK (weekday_mask BETWEEN 0 AND 127),
    start_minute SMALLINT NOT NULL CHECK (start_minute BETWEEN 0 AND 1439),
    end_minute SMALLINT NOT NULL CHECK (end_minute BETWEEN 1 AND 1440),
    tier TEXT NOT NULL CHECK (tier IN ('standard', 'priority')),
    auto_renew BOOLEAN NOT NULL DEFAULT FALSE,
    active_until TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS subscriptions_email_active_idx
    ON subscriptions(email, active_until);
CREATE INDEX IF NOT EXISTS subscriptions_active_until_idx
    ON subscriptions(active_until, tier);

CREATE TABLE IF NOT EXISTS subscription_venues (
    subscription_id TEXT NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    venue_id TEXT NOT NULL,
    PRIMARY KEY (subscription_id, venue_id)
);
CREATE INDEX IF NOT EXISTS subscription_venues_venue_idx
    ON subscription_venues(venue_id, subscription_id);

CREATE TABLE IF NOT EXISTS subscription_events (
    subscription_id TEXT NOT NULL,
    event_key TEXT NOT NULL,
    source_created_at TIMESTAMPTZ,
    imported BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (subscription_id, event_key)
);
CREATE INDEX IF NOT EXISTS subscription_events_created_idx
    ON subscription_events(created_at);

CREATE TABLE IF NOT EXISTS venue_status (
    venue_id TEXT PRIMARY KEY,
    venue_name TEXT NOT NULL,
    healthy BOOLEAN NOT NULL,
    last_inspection_at TIMESTAMPTZ NOT NULL,
    last_notification_at TIMESTAMPTZ,
    last_error TEXT,
    last_fingerprint TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS venue_status_health_idx
    ON venue_status(healthy, last_inspection_at DESC);

CREATE TABLE IF NOT EXISTS observation_receipts (
    venue_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    snapshot_revision TEXT NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    match_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (venue_id, fingerprint, snapshot_revision)
);
CREATE INDEX IF NOT EXISTS observation_receipts_last_seen_idx
    ON observation_receipts(last_seen_at);

CREATE TABLE IF NOT EXISTS availability_events (
    event_key TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL,
    venue_name TEXT NOT NULL,
    booking_date DATE NOT NULL,
    court_name TEXT NOT NULL,
    start_minute SMALLINT NOT NULL,
    end_minute SMALLINT NOT NULL,
    first_observed_at TIMESTAMPTZ NOT NULL,
    last_observed_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS availability_events_venue_date_idx
    ON availability_events(venue_id, booking_date, start_minute);
CREATE INDEX IF NOT EXISTS availability_events_last_seen_idx
    ON availability_events(last_observed_at);

CREATE TABLE IF NOT EXISTS email_outbox (
    id UUID PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    subscription_id TEXT NOT NULL,
    event_key TEXT NOT NULL,
    venue_id TEXT NOT NULL,
    email TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('standard', 'priority')),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'processing', 'retry', 'submitted', 'delivered',
            'failed', 'suppressed', 'uncertain'
        )),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    lease_id UUID,
    lease_until TIMESTAMPTZ,
    provider_message_id TEXT,
    provider_request_id TEXT,
    provider_status TEXT,
    submitted_at TIMESTAMPTZ,
    checked_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS email_outbox_due_idx
    ON email_outbox(next_attempt_at, created_at)
    WHERE status IN ('pending', 'retry');
CREATE INDEX IF NOT EXISTS email_outbox_processing_lease_idx
    ON email_outbox(lease_until)
    WHERE status = 'processing';
CREATE INDEX IF NOT EXISTS email_outbox_provider_idx
    ON email_outbox(provider_message_id)
    WHERE provider_message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS email_outbox_submitted_idx
    ON email_outbox(checked_at, submitted_at)
    WHERE status = 'submitted';
CREATE INDEX IF NOT EXISTS email_outbox_email_day_idx
    ON email_outbox(email, submitted_at)
    WHERE submitted_at IS NOT NULL;

CREATE TABLE IF NOT EXISTS daily_delivery_counters (
    delivery_day DATE NOT NULL,
    counter_key TEXT NOT NULL,
    reserved_count INTEGER NOT NULL DEFAULT 0,
    submitted_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (delivery_day, counter_key)
);

CREATE TABLE IF NOT EXISTS delivery_incidents (
    id UUID PRIMARY KEY,
    channel TEXT NOT NULL CHECK (channel IN ('email', 'wechat', 'core')),
    severity TEXT NOT NULL CHECK (severity IN ('warning', 'error', 'critical')),
    dedupe_key TEXT NOT NULL,
    reference_id TEXT,
    summary TEXT NOT NULL,
    detail TEXT,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    resolved_at TIMESTAMPTZ,
    UNIQUE(channel, dedupe_key, resolved_at)
);
CREATE INDEX IF NOT EXISTS delivery_incidents_open_idx
    ON delivery_incidents(channel, last_seen_at DESC)
    WHERE resolved_at IS NULL;

CREATE TABLE IF NOT EXISTS service_state (
    key TEXT PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO schema_migrations(version)
VALUES (1)
ON CONFLICT (version) DO NOTHING;
