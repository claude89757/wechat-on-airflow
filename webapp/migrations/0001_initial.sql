CREATE TABLE verification_challenges (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    consumed_at INTEGER,
    created_at INTEGER NOT NULL
);

CREATE INDEX verification_challenges_email_created_idx
    ON verification_challenges(email, created_at);
CREATE INDEX verification_challenges_ip_created_idx
    ON verification_challenges(ip_hash, created_at);

CREATE TABLE verified_receipts (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    masked_email TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    last_used_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    revoked_at INTEGER
);

CREATE INDEX verified_receipts_email_idx ON verified_receipts(email);

CREATE TABLE subscriptions (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    venue_ids TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_days INTEGER NOT NULL,
    active_until TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX subscriptions_email_idx ON subscriptions(email);
CREATE INDEX subscriptions_active_until_idx ON subscriptions(active, active_until);

CREATE TABLE venue_status (
    venue_id TEXT PRIMARY KEY,
    venue_name TEXT NOT NULL,
    healthy INTEGER NOT NULL DEFAULT 0,
    last_inspection_at TEXT,
    last_notification_at TEXT,
    last_error TEXT,
    updated_at TEXT NOT NULL
);

INSERT INTO venue_status (venue_id, venue_name, healthy, updated_at) VALUES
    ('szw', '深圳湾', 0, '1970-01-01T00:00:00.000Z'),
    ('sysh', '上越沙河', 0, '1970-01-01T00:00:00.000Z'),
    ('tops', 'TOPS 科技园', 0, '1970-01-01T00:00:00.000Z'),
    ('tyzx', '深圳市体育中心', 0, '1970-01-01T00:00:00.000Z'),
    ('jdwx', '金地威新', 0, '1970-01-01T00:00:00.000Z');

CREATE TABLE observed_slots (
    event_key TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL,
    court_name TEXT NOT NULL,
    booking_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    first_observed_at TEXT NOT NULL,
    last_observed_at TEXT NOT NULL
);

CREATE INDEX observed_slots_venue_date_idx
    ON observed_slots(venue_id, booking_date);

CREATE TABLE subscription_events (
    subscription_id TEXT NOT NULL,
    event_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (subscription_id, event_key)
);

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

CREATE INDEX notification_outbox_pending_idx
    ON notification_outbox(status, next_attempt_at);
CREATE INDEX notification_outbox_sent_idx
    ON notification_outbox(sent_at);
