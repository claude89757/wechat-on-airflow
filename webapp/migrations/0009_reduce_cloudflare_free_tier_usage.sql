CREATE TABLE IF NOT EXISTS observation_ingest_state (
    observation_key TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    last_forwarded_at INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS email_delivery_claims_day_status_idx
    ON email_delivery_claims(delivery_day, status);
