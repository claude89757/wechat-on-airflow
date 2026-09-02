export const FREE_TIER_SCHEMA_MARKER = "system:free-tier-schema";
export const FREE_TIER_SCHEMA_VERSION = "notification-outbox-hot-path-v1";

export const FREE_TIER_SCHEMA_SQL = `
CREATE INDEX IF NOT EXISTS notification_outbox_message_id_lookup_idx
    ON notification_outbox(message_id)
    WHERE message_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS notification_outbox_submitted_at_lookup_idx
    ON notification_outbox(provider_submitted_at, email, status, message_id)
    WHERE provider_submitted_at IS NOT NULL;

CREATE INDEX IF NOT EXISTS notification_outbox_delivered_at_lookup_idx
    ON notification_outbox(status, provider_delivered_at, email, message_id)
    WHERE provider_delivered_at IS NOT NULL;

PRAGMA optimize;
`;

type FreeTierSchemaEnv = {
  DB: D1Database;
};

type SchemaMarkerRow = {
  fingerprint: string;
};

let schemaReadyInIsolate = false;

export async function ensureFreeTierSchema(
  env: FreeTierSchemaEnv,
  now = Date.now(),
): Promise<"ready" | "applied"> {
  if (schemaReadyInIsolate) return "ready";

  const marker = await env.DB.prepare(
    `SELECT fingerprint
       FROM observation_ingest_state
      WHERE observation_key = ?`,
  ).bind(FREE_TIER_SCHEMA_MARKER).first<SchemaMarkerRow>();
  if (marker?.fingerprint === FREE_TIER_SCHEMA_VERSION) {
    schemaReadyInIsolate = true;
    return "ready";
  }

  await env.DB.exec(FREE_TIER_SCHEMA_SQL);
  await env.DB.prepare(
    `INSERT INTO observation_ingest_state
       (observation_key, fingerprint, last_forwarded_at)
     VALUES (?, ?, ?)
     ON CONFLICT(observation_key) DO UPDATE SET
       fingerprint = excluded.fingerprint,
       last_forwarded_at = excluded.last_forwarded_at`,
  ).bind(FREE_TIER_SCHEMA_MARKER, FREE_TIER_SCHEMA_VERSION, now).run();
  schemaReadyInIsolate = true;
  return "applied";
}

export function resetFreeTierSchemaCacheForTest(): void {
  schemaReadyInIsolate = false;
}
