import { describe, expect, it } from "vitest";

import {
  applyGlobalSubmittedReminderMetric,
  deploymentHealth,
  invalidatesBootstrap,
  scheduledWorkForCron,
  shanghaiDayStartIso,
  shanghaiDeliveryDay,
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
    const now = new Date("2026-08-25T15:30:00.000Z");
    expect(shanghaiDayStartIso(now)).toBe("2026-08-24T16:00:00.000Z");
    expect(shanghaiDeliveryDay(now)).toBe("2026-08-25");
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

describe("free-tier scheduling", () => {
  it("keeps recent delivery reconciliation separate from hourly maintenance", () => {
    expect(scheduledWorkForCron("*/5 * * * *")).toBe("delivery_reconcile");
    expect(scheduledWorkForCron("17 * * * *")).toBe("maintenance");
  });

  it("invalidates dashboard cache only for state-changing subscription actions", () => {
    expect(invalidatesBootstrap("POST", "/api/subscriptions")).toBe(true);
    expect(invalidatesBootstrap(
      "DELETE",
      "/api/subscriptions/9d1aca70-e4de-4c91-b3eb-1f4b26ce9181",
    )).toBe(true);
    expect(invalidatesBootstrap("POST", "/api/priority/redeem")).toBe(true);
    expect(invalidatesBootstrap("GET", "/api/bootstrap")).toBe(false);
    expect(invalidatesBootstrap("POST", "/api/internal/observations")).toBe(false);
  });
});
