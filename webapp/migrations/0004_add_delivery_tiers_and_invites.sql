CREATE TABLE user_delivery_tiers (
    email TEXT PRIMARY KEY,
    tier TEXT NOT NULL CHECK (tier IN ('standard', 'priority')),
    source_invite_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    revoked_at INTEGER
);

CREATE INDEX user_delivery_tiers_active_idx
    ON user_delivery_tiers(tier, revoked_at);

CREATE TABLE priority_invite_codes (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL UNIQUE,
    expires_at INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    note TEXT,
    created_at INTEGER NOT NULL,
    redeemed_by TEXT,
    redeemed_at INTEGER,
    redemption_id TEXT UNIQUE
);

CREATE INDEX priority_invite_codes_available_idx
    ON priority_invite_codes(active, expires_at, redeemed_at);

CREATE TABLE priority_invite_attempts (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);

CREATE INDEX priority_invite_attempts_email_created_idx
    ON priority_invite_attempts(email, created_at);
CREATE INDEX priority_invite_attempts_ip_created_idx
    ON priority_invite_attempts(ip_hash, created_at);

CREATE TABLE email_delivery_claims (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    delivery_day TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('reserved', 'sent', 'released')),
    message_id TEXT,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE INDEX email_delivery_claims_quota_idx
    ON email_delivery_claims(email, delivery_day, status, updated_at);
