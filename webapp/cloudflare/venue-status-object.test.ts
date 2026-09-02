import { describe, expect, it } from "vitest";
import { VenueStatusObject } from "./venue-status-object";
import {
  degradedDashboardFromVenueSnapshots,
  venueStatusSnapshotFromObservation,
  type VenueStatusSnapshot,
} from "./venue-status-cache";

function observation(overrides: Record<string, unknown> = {}) {
  return {
    venue_id: "szw",
    venue_name: "深圳湾",
    observation_scope: "check_and_notify_day_0",
    healthy: true,
    checked_at: "2026-09-02T18:40:00.000Z",
    error: null,
    slots: [],
    ...overrides,
  };
}

function fakeState() {
  const values = new Map<string, unknown>();
  const storage = {
    async get(key: string | string[]) {
      if (Array.isArray(key)) {
        return new Map(key.flatMap((item) => values.has(item)
          ? [[item, values.get(item)]]
          : []));
      }
      return values.get(key);
    },
    async put(key: string, value: unknown) {
      values.set(key, value);
    },
  };
  return {
    state: { storage } as unknown as DurableObjectState,
    values,
  };
}

describe("durable venue status fallback", () => {
  it("creates a validated snapshot without reading D1", async () => {
    const snapshot = await venueStatusSnapshotFromObservation(
      observation(),
      Date.parse("2026-09-02T18:40:01.000Z"),
    );

    expect(snapshot).toMatchObject({
      venueId: "szw",
      venueName: "深圳湾",
      healthy: true,
      checkedAt: "2026-09-02T18:40:00.000Z",
      slotCount: 0,
      hasError: false,
    });
    expect(snapshot?.fingerprint).toMatch(/^[0-9a-f]{64}$/);
  });

  it("stores one row per changed venue state and deduplicates repeats", async () => {
    const { state, values } = fakeState();
    const object = new VenueStatusObject(state);
    const snapshot = await venueStatusSnapshotFromObservation(
      observation(),
      Date.parse("2026-09-02T18:40:01.000Z"),
    ) as VenueStatusSnapshot;

    const first = await object.fetch(new Request(
      "https://venue-status.internal/snapshots/szw",
      { method: "PUT", body: JSON.stringify(snapshot) },
    ));
    const repeated = await object.fetch(new Request(
      "https://venue-status.internal/snapshots/szw",
      { method: "PUT", body: JSON.stringify(snapshot) },
    ));
    const listed = await object.fetch(new Request(
      "https://venue-status.internal/snapshots",
    ));

    expect(first.status).toBe(200);
    expect(await first.json()).toMatchObject({ stored: true, deduplicated: false });
    expect(await repeated.json()).toMatchObject({ stored: false, deduplicated: true });
    expect(values.size).toBe(1);
    expect(await listed.json()).toMatchObject({ snapshots: [{ venueId: "szw" }] });
  });

  it("builds a partial dashboard that preserves known Airflow venue health", async () => {
    const snapshot = await venueStatusSnapshotFromObservation(
      observation(),
      Date.parse("2026-09-02T18:40:01.000Z"),
    ) as VenueStatusSnapshot;
    const dashboard = degradedDashboardFromVenueSnapshots(
      [snapshot],
      {},
      true,
      new Date("2026-09-02T18:41:00.000Z"),
    );

    expect(dashboard?.dataStatus).toMatchObject({
      stale: true,
      source: "edge-cache",
      reason: "data_store_unavailable",
      retryAt: "2026-09-03T00:00:00.000Z",
    });
    expect(dashboard?.identity).toMatchObject({
      verified: true,
      maskedEmail: "本机已验证邮箱",
    });
    expect(dashboard?.venues).toEqual([
      expect.objectContaining({ id: "szw", healthy: true }),
    ]);
    expect(dashboard?.metrics.totalVenues).toBe(26);
  });
});
