-- ISO weekday bit mask: Monday = 1, ..., Sunday = 64. Existing rows remain active every day.
ALTER TABLE subscriptions
    ADD COLUMN weekday_mask INTEGER NOT NULL DEFAULT 127
    CHECK (weekday_mask BETWEEN 1 AND 127);
