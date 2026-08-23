CREATE TABLE user_profiles (
    email TEXT PRIMARY KEY,
    masked_email TEXT NOT NULL,
    first_verified_at INTEGER NOT NULL,
    last_verified_at INTEGER NOT NULL,
    last_login_at INTEGER NOT NULL,
    last_active_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

INSERT OR IGNORE INTO user_profiles
    (email, masked_email, first_verified_at, last_verified_at,
     last_login_at, last_active_at, created_at, updated_at)
SELECT email,
       MAX(masked_email),
       MIN(created_at),
       MAX(created_at),
       MAX(last_used_at),
       MAX(last_used_at),
       MIN(created_at),
       MAX(last_used_at)
  FROM verified_receipts
 GROUP BY email;

CREATE TABLE user_roles (
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin')),
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    revoked_at INTEGER,
    PRIMARY KEY (email, role)
);
CREATE INDEX user_roles_active_idx ON user_roles(role, revoked_at);

INSERT INTO user_roles (email, role, created_at, updated_at, revoked_at)
VALUES ('claudexzt@gmail.com', 'admin', unixepoch() * 1000, unixepoch() * 1000, NULL)
ON CONFLICT(email, role) DO UPDATE SET
  updated_at = excluded.updated_at,
  revoked_at = NULL;

ALTER TABLE priority_invite_codes ADD COLUMN encrypted_code TEXT;
ALTER TABLE priority_invite_codes ADD COLUMN encryption_iv TEXT;
ALTER TABLE priority_invite_codes ADD COLUMN code_hint TEXT;
ALTER TABLE priority_invite_codes ADD COLUMN updated_at INTEGER;
ALTER TABLE priority_invite_codes ADD COLUMN deleted_at INTEGER;
UPDATE priority_invite_codes SET updated_at = created_at WHERE updated_at IS NULL;

ALTER TABLE notification_outbox ADD COLUMN provider_request_id TEXT;
ALTER TABLE notification_outbox ADD COLUMN provider_status TEXT;
ALTER TABLE notification_outbox ADD COLUMN provider_submitted_at TEXT;
ALTER TABLE notification_outbox ADD COLUMN provider_delivered_at TEXT;
ALTER TABLE notification_outbox ADD COLUMN provider_failed_at TEXT;
ALTER TABLE notification_outbox ADD COLUMN provider_checked_at INTEGER;
ALTER TABLE notification_outbox ADD COLUMN provider_error TEXT;

UPDATE notification_outbox
   SET status = 'submitted',
       provider_status = 'legacy_unverified',
       provider_submitted_at = COALESCE(sent_at, created_at)
 WHERE status = 'sent';
UPDATE venue_status SET last_notification_at = NULL;

CREATE INDEX notification_outbox_provider_status_idx
    ON notification_outbox(status, provider_checked_at, provider_submitted_at);

CREATE TABLE system_email_outbox (
    id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    email_type TEXT NOT NULL CHECK (email_type IN ('subscription_expiry')),
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at INTEGER NOT NULL,
    provider_message_id TEXT,
    provider_request_id TEXT,
    provider_status TEXT,
    submitted_at TEXT,
    delivered_at TEXT,
    failed_at TEXT,
    provider_checked_at INTEGER,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX system_email_outbox_pending_idx
    ON system_email_outbox(status, next_attempt_at);
CREATE INDEX system_email_outbox_provider_idx
    ON system_email_outbox(status, provider_checked_at, submitted_at);
