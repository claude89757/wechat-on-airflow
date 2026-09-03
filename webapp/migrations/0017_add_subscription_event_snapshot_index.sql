CREATE INDEX IF NOT EXISTS subscription_events_created_snapshot_idx
    ON subscription_events(created_at, subscription_id, event_key);

PRAGMA optimize;
