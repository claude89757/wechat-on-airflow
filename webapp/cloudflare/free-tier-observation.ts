import { VENUES, type VenueId } from "./domain";
import {
  observationSnapshot,
  type ObservationSnapshot,
} from "./observation-dedupe";

type ObservationStateRow = {
  fingerprint: string;
};

export type FreeTierObservationEnvelope = {
  snapshot: ObservationSnapshot;
  venueId: VenueId;
  venueName: string;
  healthy: boolean;
  checkedAt: string;
  error: string | null;
};

export type FreeTierObservationAction = "forward" | "skip";

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
): FreeTierObservationAction {
  return current?.fingerprint === snapshot.fingerprint ? "skip" : "forward";
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
    `SELECT fingerprint
       FROM observation_ingest_state
      WHERE observation_key = ?`,
  ).bind(envelope.snapshot.key).first<ObservationStateRow>();
  return {
    action: classifyFreeTierObservation(envelope.snapshot, current),
    envelope,
  };
}
