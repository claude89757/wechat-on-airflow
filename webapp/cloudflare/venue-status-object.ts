import { VENUES, type VenueId } from "./domain";
import {
  isVenueStatusSnapshot,
  type VenueStatusSnapshot,
} from "./venue-status-cache";

const SNAPSHOT_PREFIX = "venue:";

function snapshotKey(venueId: VenueId): string {
  return `${SNAPSHOT_PREFIX}${venueId}`;
}

function json(payload: unknown, status = 200): Response {
  return Response.json(payload, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export class VenueStatusObject {
  constructor(private readonly state: DurableObjectState) {}

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const venueIds = Object.keys(VENUES) as VenueId[];

    if (request.method === "GET" && url.pathname === "/snapshots") {
      const keys = venueIds.map(snapshotKey);
      const stored = await this.state.storage.get<VenueStatusSnapshot>(keys);
      const snapshots = venueIds.flatMap((venueId) => {
        const snapshot = stored.get(snapshotKey(venueId));
        return snapshot && isVenueStatusSnapshot(snapshot) ? [snapshot] : [];
      });
      return json({ snapshots });
    }

    const match = url.pathname.match(/^\/snapshots\/([a-z0-9_]+)$/);
    if (request.method === "PUT" && match) {
      const venueId = match[1] as VenueId;
      if (!(venueId in VENUES)) return json({ error: "venue_not_found" }, 404);

      let payload: unknown;
      try {
        payload = await request.json<unknown>();
      } catch {
        return json({ error: "invalid_json" }, 400);
      }
      if (!isVenueStatusSnapshot(payload) || payload.venueId !== venueId) {
        return json({ error: "invalid_snapshot" }, 400);
      }

      const key = snapshotKey(venueId);
      const current = await this.state.storage.get<VenueStatusSnapshot>(key);
      if (current && isVenueStatusSnapshot(current) && current.fingerprint === payload.fingerprint) {
        return json({ stored: false, deduplicated: true });
      }
      await this.state.storage.put(key, payload);
      return json({ stored: true, deduplicated: false });
    }

    return json({ error: "not_found" }, 404);
  }
}
