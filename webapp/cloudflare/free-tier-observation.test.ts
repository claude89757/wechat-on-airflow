import { describe, expect, it } from "vitest";

import { OBSERVATION_HEARTBEAT_MS } from "./observation-dedupe";
import {
  classifyFreeTierObservation,
  freeTierObservationEnvelope,
} from "./free-tier-observation";

const now = Date.parse("2026-09-02T09:00:30.000Z");
const observation = {
  venue_id: "szw",
  venue_name: "深圳湾",
  observation_scope: "check_and_notify_day_0",
  healthy: true,
  checked_at: "2026-09-02T09:00:00.000Z",
  error: null,
  slots: [
    {
      date: "2026-09-03",
      court_name: "1号场",
      start_time: "18:00",
      end_time: "19:00",
    },
  ],
};

describe("free-tier observation policy", () => {
  it("accepts only a canonical known venue payload", async () => {
    const envelope = await freeTierObservationEnvelope(observation, now);
    expect(envelope?.venueId).toBe("szw");
    expect(envelope?.venueName).toBe("深圳湾");
    expect(envelope?.checkedAt).toBe("2026-09-02T09:00:00.000Z");

    expect(await freeTierObservationEnvelope({
      ...observation,
      venue_name: "wrong venue",
    }, now)).toBeNull();
    expect(await freeTierObservationEnvelope({
      ...observation,
      venue_id: "unknown",
    }, now)).toBeNull();
  });

  it("forwards changes, skips recent duplicates, and emits only a light heartbeat", async () => {
    const envelope = await freeTierObservationEnvelope(observation, now);
    if (!envelope) throw new Error("expected a valid envelope");

    expect(classifyFreeTierObservation(envelope.snapshot, null, now)).toBe("forward");
    expect(classifyFreeTierObservation(envelope.snapshot, {
      fingerprint: "different",
      last_forwarded_at: now,
    }, now)).toBe("forward");
    expect(classifyFreeTierObservation(envelope.snapshot, {
      fingerprint: envelope.snapshot.fingerprint,
      last_forwarded_at: now - 15_000,
    }, now)).toBe("skip");
    expect(classifyFreeTierObservation(envelope.snapshot, {
      fingerprint: envelope.snapshot.fingerprint,
      last_forwarded_at: now - OBSERVATION_HEARTBEAT_MS,
    }, now)).toBe("heartbeat");
  });
});
