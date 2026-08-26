import { describe, expect, it } from "vitest";

import {
  OBSERVATION_HEARTBEAT_MS,
  observationSnapshot,
  shouldSkipObservation,
} from "./observation-dedupe";

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

describe("observation fingerprint", () => {
  it("ignores checked_at and slot ordering", async () => {
    const first = await observationSnapshot(baseObservation);
    const second = await observationSnapshot({
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
    const first = await observationSnapshot(baseObservation);
    const second = await observationSnapshot({
      ...baseObservation,
      slots: baseObservation.slots.slice(0, 1),
    });
    expect(first?.fingerprint).not.toBe(second?.fingerprint);
  });

  it("forwards availability that disappears and then reappears", async () => {
    const available = await observationSnapshot(baseObservation);
    const empty = await observationSnapshot({
      ...baseObservation,
      slots: [],
    });
    const restored = await observationSnapshot({
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
      last_forwarded_at: 1_000_000,
    }, 1_015_000)).toBe(false);
  });

  it("keeps an unchanged heartbeat inside the venue freshness window", async () => {
    const snapshot = await observationSnapshot(baseObservation);
    if (!snapshot) throw new Error("expected a valid snapshot");
    const forwardedAt = 1_000_000;
    const current = {
      fingerprint: snapshot.fingerprint,
      last_forwarded_at: forwardedAt,
    };
    expect(shouldSkipObservation(snapshot, current, forwardedAt + 15_000)).toBe(true);
    expect(shouldSkipObservation(
      snapshot,
      current,
      forwardedAt + OBSERVATION_HEARTBEAT_MS,
    )).toBe(false);
  });

  it("separates parallel day tasks for the same venue", async () => {
    const first = await observationSnapshot(baseObservation);
    const second = await observationSnapshot({
      ...baseObservation,
      observation_scope: "check_and_notify_day_1",
    });
    expect(first?.key).toBe("v2:szw:check_and_notify_day_0");
    expect(second?.key).toBe("v2:szw:check_and_notify_day_1");
  });

  it("uses a safe compatibility scope for old publishers", async () => {
    const { observation_scope: _scope, ...legacyObservation } = baseObservation;
    const snapshot = await observationSnapshot(legacyObservation);
    expect(snapshot?.key).toBe("v2:szw:default");
  });
});
