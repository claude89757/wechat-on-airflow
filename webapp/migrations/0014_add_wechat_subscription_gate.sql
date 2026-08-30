CREATE TABLE IF NOT EXISTS wechat_venue_gates (
    venue_id TEXT PRIMARY KEY,
    allowed INTEGER NOT NULL DEFAULT 0 CHECK (allowed IN (0, 1)),
    evaluated_at INTEGER NOT NULL,
    revision INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS wechat_venue_gates_allowed_idx
    ON wechat_venue_gates(allowed, evaluated_at);
