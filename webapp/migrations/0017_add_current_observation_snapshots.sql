CREATE TABLE IF NOT EXISTS current_observation_snapshots (
    observation_key TEXT PRIMARY KEY,
    venue_id TEXT NOT NULL,
    venue_name TEXT NOT NULL,
    healthy INTEGER NOT NULL,
    checked_at TEXT NOT NULL,
    error TEXT,
    slots_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS current_observation_snapshots_venue_idx
    ON current_observation_snapshots(venue_id);
