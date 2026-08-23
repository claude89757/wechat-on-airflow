ALTER TABLE subscriptions ADD COLUMN term_code TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE subscriptions ADD COLUMN auto_renew INTEGER NOT NULL DEFAULT 0;
ALTER TABLE subscriptions ADD COLUMN dedupe_key TEXT;

UPDATE subscriptions
   SET term_code = CASE
     WHEN duration_days BETWEEN 7 AND 14 THEN CAST(duration_days AS TEXT) || 'd'
     ELSE '14d'
   END
 WHERE term_code = 'legacy';

CREATE INDEX subscriptions_term_renewal_idx
    ON subscriptions(active, auto_renew, active_until);
CREATE UNIQUE INDEX subscriptions_active_dedupe_idx
    ON subscriptions(email, dedupe_key)
 WHERE active = 1 AND dedupe_key IS NOT NULL;
