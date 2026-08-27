const OBSERVATION_KEY_VERSION = "v2";

export const OBSERVATION_HEARTBEAT_MS = 5 * 60_000;

type CanonicalObservationSlot = {
  date: string;
  courtName: string;
  startTime: string;
  endTime: string;
};

type ObservationStateRow = {
  fingerprint: string;
  last_forwarded_at: number;
};

export type ObservationSnapshot = {
  key: string;
  fingerprint: string;
  venueId: string;
  observationScope: string;
  slotCount: number;
};

export type ObservationDedupeDecision = {
  action: "forward" | "skip";
  snapshot: ObservationSnapshot | null;
};

function stringField(
  candidate: Record<string, unknown>,
  snakeCase: string,
  camelCase: string,
): string {
  return String(candidate[snakeCase] ?? candidate[camelCase] ?? "").trim();
}

function canonicalSlot(value: unknown): CanonicalObservationSlot | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  const date = String(candidate.date ?? "").trim();
  const courtName = stringField(candidate, "court_name", "courtName");
  const startTime = stringField(candidate, "start_time", "startTime");
  const endTime = stringField(candidate, "end_time", "endTime");
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(date)
    || !courtName
    || courtName.length > 120
    || !/^\d{2}:\d{2}$/.test(startTime)
    || !/^\d{2}:\d{2}$/.test(endTime)
  ) {
    return null;
  }
  return { date, courtName, startTime, endTime };
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export async function observationSnapshot(
  payload: unknown,
  now = Date.now(),
): Promise<ObservationSnapshot | null> {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const candidate = payload as Record<string, unknown>;
  const venueId = stringField(candidate, "venue_id", "venueId");
  const venueName = stringField(candidate, "venue_name", "venueName");
  const explicitScope = stringField(
    candidate,
    "observation_scope",
    "observationScope",
  );
  const observationScope = explicitScope || "default";
  const checkedAt = stringField(candidate, "checked_at", "checkedAt");
  const checkedAtMs = Date.parse(checkedAt);
  if (
    !venueId
    || venueId.length > 64
    || !venueName
    || venueName.length > 120
    || observationScope.length > 120
    || !checkedAt
    || !Number.isFinite(checkedAtMs)
    || Math.abs(now - checkedAtMs) > 86_400_000
  ) {
    return null;
  }
  if (!Array.isArray(candidate.slots) || candidate.slots.length > 200) return null;

  const slots: CanonicalObservationSlot[] = [];
  for (const value of candidate.slots) {
    const slot = canonicalSlot(value);
    if (!slot) return null;
    slots.push(slot);
  }

  const uniqueSlots = Array.from(new Map<string, CanonicalObservationSlot>(
    slots.map((slot): [string, CanonicalObservationSlot] => [
      [slot.date, slot.courtName, slot.startTime, slot.endTime].join("|"),
      slot,
    ]),
  ).values()).sort((left, right) =>
    [left.date, left.courtName, left.startTime, left.endTime].join("|")
      .localeCompare([right.date, right.courtName, right.startTime, right.endTime].join("|"))
  );
  const error = candidate.error ? String(candidate.error).slice(0, 300) : null;
  const fingerprint = await sha256Hex(JSON.stringify({
    venueId,
    venueName,
    observationScope,
    healthy: candidate.healthy === true,
    error,
    slots: uniqueSlots,
  }));

  return {
    key: `${OBSERVATION_KEY_VERSION}:${venueId}:${observationScope}`,
    fingerprint,
    venueId,
    observationScope,
    slotCount: uniqueSlots.length,
  };
}

export function shouldSkipObservation(
  snapshot: ObservationSnapshot,
  current: ObservationStateRow | null,
  now: number,
  heartbeatMs = OBSERVATION_HEARTBEAT_MS,
): boolean {
  return Boolean(
    current
    && current.fingerprint === snapshot.fingerprint
    && now - Number(current.last_forwarded_at) < heartbeatMs,
  );
}

export async function decideObservationDedupe(
  db: D1Database,
  payload: unknown,
  now = Date.now(),
): Promise<ObservationDedupeDecision> {
  const snapshot = await observationSnapshot(payload, now);
  if (!snapshot) return { action: "forward", snapshot: null };
  const current = await db.prepare(
    `SELECT fingerprint, last_forwarded_at
       FROM observation_ingest_state
      WHERE observation_key = ?`,
  ).bind(snapshot.key).first<ObservationStateRow>();
  return {
    action: shouldSkipObservation(snapshot, current, now) ? "skip" : "forward",
    snapshot,
  };
}

export async function recordForwardedObservation(
  db: D1Database,
  snapshot: ObservationSnapshot,
  now = Date.now(),
): Promise<void> {
  await db.prepare(
    `INSERT INTO observation_ingest_state
       (observation_key, fingerprint, last_forwarded_at)
     VALUES (?, ?, ?)
     ON CONFLICT(observation_key) DO UPDATE SET
       fingerprint = excluded.fingerprint,
       last_forwarded_at = excluded.last_forwarded_at`,
  ).bind(snapshot.key, snapshot.fingerprint, now).run();
}
