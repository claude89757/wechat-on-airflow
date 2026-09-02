import { VENUES, type VenueId } from "./domain";
import {
  OBSERVATION_HEARTBEAT_MS,
  observationSnapshot,
  type ObservationSnapshot,
} from "./observation-dedupe";

type ObservationStateRow = {
  fingerprint: string;
  last_forwarded_at: number;
};

export type FreeTierObservationEnvelope = {
  snapshot: ObservationSnapshot;
  venueId: VenueId;
  venueName: string;
  healthy: boolean;
  checkedAt: string;
  error: string | null;
};

export type FreeTierObservationAction = "forward" | "skip" | "heartbeat";

function stringField(
  candidate: Record<string, unknown>,
  snakeCase: string,
  camelCase: string,
): string {
  return String(candidate[snakeCase] ?? candidate[camelCase] ?? "").trim();
}

export async function freeTierObservationEnvelope(
  payload: unknown,
  now = Date.now(),
): Promise<FreeTierObservationEnvelope | null> {
  const snapshot = await observationSnapshot(payload, now);
  if (!snapshot || !payload || typeof payload !== "object" || Array.isArray(payload)) {
    return null;
  }
  if (!(snapshot.venueId in VENUES)) return null;

  const candidate = payload as Record<string, unknown>;
  const venueId = snapshot.venueId as VenueId;
  const venueName = stringField(candidate, "venue_name", "venueName");
  if (venueName !== VENUES[venueId]) return null;

  const checkedAtValue = stringField(candidate, "checked_at", "checkedAt");
  const checkedAtMs = Date.parse(checkedAtValue);
  if (!Number.isFinite(checkedAtMs)) return null;

  return {
    snapshot,
    venueId,
    venueName,
    healthy: candidate.healthy === true,
    checkedAt: new Date(checkedAtMs).toISOString(),
    error: candidate.error ? String(candidate.error).slice(0, 300) : null,
  };
}

export function classifyFreeTierObservation(
  snapshot: ObservationSnapshot,
  current: ObservationStateRow | null,
  now: number,
  heartbeatMs = OBSERVATION_HEARTBEAT_MS,
): FreeTierObservationAction {
  if (!current || current.fingerprint !== snapshot.fingerprint) return "forward";
  return now - Number(current.last_forwarded_at) < heartbeatMs
    ? "skip"
    : "heartbeat";
}

export async function applyFreeTierObservationPolicy(
  db: D1Database,
  payload: unknown,
  now = Date.now(),
): Promise<{
  action: FreeTierObservationAction;
  envelope: FreeTierObservationEnvelope | null;
}> {
  const envelope = await freeTierObservationEnvelope(payload, now);
  if (!envelope) return { action: "forward", envelope: null };

  const current = await db.prepare(
    `SELECT fingerprint, last_forwarded_at
       FROM observation_ingest_state
      WHERE observation_key = ?`,
  ).bind(envelope.snapshot.key).first<ObservationStateRow>();
  const action = classifyFreeTierObservation(envelope.snapshot, current, now);
  if (action !== "heartbeat" || !current) return { action, envelope };

  const nowIso = new Date(now).toISOString();
  const results = await db.batch([
    db.prepare(
      `UPDATE observation_ingest_state
          SET last_forwarded_at = ?
        WHERE observation_key = ?
          AND fingerprint = ?
          AND last_forwarded_at = ?`,
    ).bind(
      now,
      envelope.snapshot.key,
      envelope.snapshot.fingerprint,
      current.last_forwarded_at,
    ),
    db.prepare(
      `INSERT INTO venue_status
         (venue_id, venue_name, healthy, last_inspection_at, last_error, updated_at)
       SELECT ?, ?, ?, ?, ?, ?
        WHERE EXISTS (
          SELECT 1
            FROM observation_ingest_state
           WHERE observation_key = ?
             AND fingerprint = ?
             AND last_forwarded_at = ?
        )
       ON CONFLICT(venue_id) DO UPDATE SET
         venue_name = excluded.venue_name,
         healthy = excluded.healthy,
         last_inspection_at = excluded.last_inspection_at,
         last_error = excluded.last_error,
         updated_at = excluded.updated_at`,
    ).bind(
      envelope.venueId,
      envelope.venueName,
      envelope.healthy ? 1 : 0,
      envelope.checkedAt,
      envelope.error,
      nowIso,
      envelope.snapshot.key,
      envelope.snapshot.fingerprint,
      now,
    ),
  ]);

  const claimed = Number(results[0]?.meta.changes || 0) > 0;
  const venueUpdated = Number(results[1]?.meta.changes || 0) > 0;
  return {
    action: claimed && venueUpdated ? "heartbeat" : "skip",
    envelope,
  };
}
