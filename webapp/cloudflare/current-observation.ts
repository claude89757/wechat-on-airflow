import {
  formatSlotLine,
  sha256Hex,
  slotMatchesTimeRange,
  slotMatchesWeekday,
  validateSlotObservation,
  type SlotObservation,
  type VenueId,
} from "./domain";

export type CurrentObservationSnapshotInput = {
  observationKey: string;
  venueId: VenueId;
  venueName: string;
  healthy: boolean;
  checkedAt: string;
  error: string | null;
  slots: SlotObservation[];
};

export type CurrentSnapshotRow = {
  observation_key: string;
  venue_id: VenueId;
  venue_name: string;
  healthy: number;
  checked_at: string;
  slots_json: string;
};

export type CurrentSubscriptionMatchInput = {
  id: string;
  email: string;
  venueIds: VenueId[];
  weekdayMask: number;
  startTime: string;
  endTime: string;
};

export type CurrentObservationMatch = {
  eventKey: string;
  venueId: VenueId;
  line: string;
};

const MAX_CURRENT_MATCHES = 500;
const MAX_BATCH_STATEMENTS = 100;

function currentSlot(slot: SlotObservation, now: Date): boolean {
  const endAt = Date.parse(`${slot.date}T${slot.endTime}:00+08:00`);
  return Number.isFinite(endAt) && endAt > now.getTime();
}

function parseSnapshotSlots(row: CurrentSnapshotRow): SlotObservation[] {
  try {
    const value = JSON.parse(row.slots_json) as unknown;
    if (!Array.isArray(value)) return [];
    return value.map(validateSlotObservation);
  } catch {
    return [];
  }
}

export function currentObservationSnapshotStatement(
  db: D1Database,
  observation: CurrentObservationSnapshotInput,
  updatedAt = new Date().toISOString(),
): D1PreparedStatement {
  return db.prepare(
    `INSERT INTO current_observation_snapshots
       (observation_key, venue_id, venue_name, healthy, checked_at, error,
        slots_json, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(observation_key) DO UPDATE SET
       venue_id = excluded.venue_id,
       venue_name = excluded.venue_name,
       healthy = excluded.healthy,
       checked_at = excluded.checked_at,
       error = excluded.error,
       slots_json = excluded.slots_json,
       updated_at = excluded.updated_at`,
  ).bind(
    observation.observationKey,
    observation.venueId,
    observation.venueName,
    observation.healthy ? 1 : 0,
    observation.checkedAt,
    observation.error,
    JSON.stringify(observation.slots),
    updatedAt,
  );
}

export async function currentSnapshotMatches(
  rows: CurrentSnapshotRow[],
  subscription: CurrentSubscriptionMatchInput,
  now = new Date(),
): Promise<CurrentObservationMatch[]> {
  const selected = new Set(subscription.venueIds);
  const seen = new Set<string>();
  const matches: CurrentObservationMatch[] = [];

  for (const row of rows) {
    if (!row.healthy || !selected.has(row.venue_id)) continue;
    for (const slot of parseSnapshotSlots(row)) {
      if (!currentSlot(slot, now)) continue;
      if (!slotMatchesWeekday(slot, subscription.weekdayMask)) continue;
      if (!slotMatchesTimeRange(slot, subscription.startTime, subscription.endTime)) continue;
      const eventKey = await sha256Hex([
        row.venue_id,
        slot.date,
        slot.courtName,
        slot.startTime,
        slot.endTime,
      ].join("|"));
      if (seen.has(eventKey)) continue;
      seen.add(eventKey);
      matches.push({
        eventKey,
        venueId: row.venue_id,
        line: formatSlotLine(row.venue_name, slot),
      });
      if (matches.length >= MAX_CURRENT_MATCHES) return matches;
    }
  }
  return matches;
}

async function currentSnapshotRows(
  db: D1Database,
  venueIds: VenueId[],
): Promise<CurrentSnapshotRow[]> {
  if (!venueIds.length) return [];
  const placeholders = venueIds.map(() => "?").join(", ");
  return (
    await db.prepare(
      `SELECT observation_key, venue_id, venue_name, healthy, checked_at, slots_json
         FROM current_observation_snapshots
        WHERE healthy = 1
          AND venue_id IN (${placeholders})`,
    ).bind(...venueIds).all<CurrentSnapshotRow>()
  ).results;
}

export async function enqueueCurrentSnapshotMatches(
  db: D1Database,
  subscription: CurrentSubscriptionMatchInput,
  now = new Date(),
): Promise<number> {
  const rows = await currentSnapshotRows(db, subscription.venueIds);
  const matches = await currentSnapshotMatches(rows, subscription, now);
  if (!matches.length) return 0;

  const nowIso = now.toISOString();
  const statements: D1PreparedStatement[] = [];
  for (const match of matches) {
    statements.push(
      db.prepare(
        `INSERT OR IGNORE INTO subscription_events
           (subscription_id, event_key, created_at)
         VALUES (?, ?, ?)`,
      ).bind(subscription.id, match.eventKey, nowIso),
      db.prepare(
        `INSERT OR IGNORE INTO notification_outbox
           (id, subscription_id, event_key, venue_id, email, subject, body,
            status, attempt_count, next_attempt_at, created_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)`,
      ).bind(
        crypto.randomUUID(),
        subscription.id,
        match.eventKey,
        match.venueId,
        subscription.email,
        match.line,
        match.line,
        now.getTime(),
        nowIso,
      ),
    );
  }

  for (let index = 0; index < statements.length; index += MAX_BATCH_STATEMENTS) {
    await db.batch(statements.slice(index, index + MAX_BATCH_STATEMENTS));
  }
  return matches.length;
}
