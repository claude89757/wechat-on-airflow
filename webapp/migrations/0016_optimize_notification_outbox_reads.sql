CREATE INDEX IF NOT EXISTS notification_outbox_message_id_lookup_idx
    ON notification_outbox(message_id)
    WHERE message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS notification_outbox_submitted_at_lookup_idx
    ON notification_outbox(provider_submitted_at, email, status, message_id)
    WHERE provider_submitted_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS notification_outbox_delivered_at_lookup_idx
    ON notification_outbox(status, provider_delivered_at, email, message_id)
    WHERE provider_delivered_at IS NOT NULL;
