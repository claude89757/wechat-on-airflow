import { describe, expect, it } from "vitest";

import {
  applyGlobalSubmittedReminderMetric,
  deploymentHealth,
  shanghaiDayStartIso,
} from "./deployment-entry";

describe("deployment entry health", () => {
  it("reports only an exact deployed commit", () => {
    const commit = "a".repeat(40);
    expect(deploymentHealth(commit)).toEqual({
      ok: true,
      service: "zacks-tennis-alerts",
      deploymentCommit: commit,
    });
    expect(deploymentHealth("main").deploymentCommit).toBe("unknown");
  });
});

describe("aggregate reminder metric", () => {
  it("uses the Shanghai calendar-day boundary", () => {
    expect(shanghaiDayStartIso(new Date("2026-08-25T15:30:00.000Z")))
      .toBe("2026-08-24T16:00:00.000Z");
  });

  it("replaces only the aggregate reminder count", () => {
    expect(applyGlobalSubmittedReminderMetric({
      metrics: {
        activeSubscriptions: 18,
        remindersToday: 0,
        healthyVenues: 8,
        totalVenues: 8,
      },
      identity: {
        submittedToday: 24,
        deliveredToday: 0,
      },
    }, 156)).toEqual({
      metrics: {
        activeSubscriptions: 18,
        remindersToday: 156,
        healthyVenues: 8,
        totalVenues: 8,
      },
      identity: {
        submittedToday: 24,
        deliveredToday: 0,
      },
    });
  });
});
