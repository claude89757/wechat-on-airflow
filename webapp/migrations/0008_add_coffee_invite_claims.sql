CREATE TABLE coffee_invite_sessions (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    ip_hash TEXT NOT NULL,
    shown_at INTEGER NOT NULL,
    claimable_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    consumed_at INTEGER,
    created_at INTEGER NOT NULL,
    CHECK (claimable_at >= shown_at + 5000),
    CHECK (expires_at > claimable_at)
);

CREATE INDEX coffee_invite_sessions_email_created_idx
    ON coffee_invite_sessions(email, created_at);
CREATE INDEX coffee_invite_sessions_ip_created_idx
    ON coffee_invite_sessions(ip_hash, created_at);
CREATE INDEX coffee_invite_sessions_expiry_idx
    ON coffee_invite_sessions(expires_at);

CREATE TABLE coffee_invite_claims (
    email TEXT PRIMARY KEY,
    session_id TEXT NOT NULL UNIQUE,
    invite_id TEXT NOT NULL UNIQUE,
    ip_hash TEXT NOT NULL,
    claimed_at INTEGER NOT NULL
);

CREATE INDEX coffee_invite_claims_ip_claimed_idx
    ON coffee_invite_claims(ip_hash, claimed_at);
