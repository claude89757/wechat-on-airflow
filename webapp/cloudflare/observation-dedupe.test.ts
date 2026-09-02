import { describe, expect, it } from "vitest";

import {
  observationSnapshot,
  shouldSkipObservation,
} from "./observation-dedupe";

const OBSERVATION_NOW = Date.parse("2026-08-27T01:00:30.000Z");
const baseObservation = {
  venue_id: "szw",
  venue_name: "深圳湾",
  observation_scope: "check_and_notify_day_0",
  healthy: true,
  checked_at: "2026-08-27T01:00:00.000Z",
  error: null,
  slots: [
    {
      date: "2026-08-28",
      court_name: "室外1号场",
      start_time: "18:00",
      end_time: "19:00",
    },
    {
      date: "2026-08-28",
      court_name: "室外2号场",
      start_time: "19:00",
      end_time: "20:00",
    },
  ],
};

function snapshot(payload: unknown) {
  return observationSnapshot(payload, OBSERVATION_NOW);
}

describe("observation fingerprint", () => {
  it("ignores checked_at and slot ordering", async () => {
    const first = await snapshot(baseObservation);
    const second = await snapshot({
      ...baseObservation,
      checked_at: "2026-08-27T01:00:15.000Z",
      slots: [...baseObservation.slots].reverse(),
    });
    expect(first).not.toBeNull();
    expect(second).not.toBeNull();
    expect(second?.key).toBe(first?.key);
    expect(second?.fingerprint).toBe(first?.fingerprint);
  });

  it("forwards a real availability change immediately", async () => {
    const first = await snapshot(baseObservation);
    const second = await snapshot({
      ...baseObservation,
      slots: baseObservation.slots.slice(0, 1),
    });
    expect(first?.fingerprint).not.toBe(second?.fingerprint);
  });

  it("forwards availability that disappears and then reappears", async () => {
    const available = await snapshot(baseObservation);
    const empty = await snapshot({
      ...baseObservation,
      slots: [],
    });
    const restored = await snapshot({
      ...baseObservation,
      checked_at: "2026-08-27T01:01:00.000Z",
    });
    expect(available?.key).toBe(empty?.key);
    expect(restored?.key).toBe(empty?.key);
    expect(available?.fingerprint).not.toBe(empty?.fingerprint);
    expect(restored?.fingerprint).toBe(available?.fingerprint);
    if (!restored || !empty) throw new Error("expected valid snapshots");
    expect(shouldSkipObservation(restored, {
      fingerprint: empty.fingerprint,
    })).toBe(false);
  });

  it("skips an identical observation without any time-based heartbeat", async () => {
    const observation = await snapshot(baseObservation);
    if (!observation) throw new Error("expected a valid snapshot");
    const current = { fingerprint: observation.fingerprint };

    expect(shouldSkipObservation(observation, current)).toBe(true);
    expect(shouldSkipObservation(observation, current)).toBe(true);
  });

  it("separates parallel day tasks for the same venue", async () => {
    const first = await snapshot(baseObservation);
    const second = await snapshot({
      ...baseObservation,
      observation_scope: "check_and_notify_day_1",
    });
    expect(first?.key).toBe("v2:szw:check_and_notify_day_0");
    expect(second?.key).toBe("v2:szw:check_and_notify_day_1");
  });

  it("uses a safe compatibility scope for old publishers", async () => {
    const { observation_scope: _scope, ...legacyObservation } = baseObservation;
    const observation = await snapshot(legacyObservation);
    expect(observation?.key).toBe("v2:szw:default");
  });

  it("forwards invalid or stale timestamps to the canonical validator", async () => {
    expect(await snapshot({
      ...baseObservation,
      checked_at: "not-a-date",
    })).toBeNull();
    expect(await snapshot({
      ...baseObservation,
      checked_at: "2026-08-25T01:00:00.000Z",
    })).toBeNull();
  });
});
