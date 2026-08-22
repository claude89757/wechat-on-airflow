import { describe, expect, it } from "vitest";

import {
  deliveryLimitForTier,
  deliveryTierLimits,
  deliveryTierRank,
  normalizeDeliveryTier,
  remainingDailyDeliveries,
} from "./delivery-tiers";

describe("subscriber email delivery tiers", () => {
  it("uses the configured product defaults", () => {
    expect(deliveryTierLimits({})).toEqual({ standard: 30, priority: 100 });
  });

  it("honors positive integer limits and never makes priority lower", () => {
    expect(deliveryTierLimits({
      STANDARD_DAILY_EMAIL_LIMIT: "50",
      PRIORITY_DAILY_EMAIL_LIMIT: "40",
    })).toEqual({ standard: 50, priority: 50 });
  });

  it("falls back for malformed limits", () => {
    expect(deliveryLimitForTier(
      {
        STANDARD_DAILY_EMAIL_LIMIT: "0",
        PRIORITY_DAILY_EMAIL_LIMIT: "not-a-number",
      },
      "priority",
    )).toBe(100);
  });

  it("normalizes unknown tiers to standard", () => {
    expect(normalizeDeliveryTier("priority")).toBe("priority");
    expect(normalizeDeliveryTier("vip")).toBe("standard");
  });

  it("computes remaining quota and prioritizes priority users", () => {
    expect(remainingDailyDeliveries(2, 30)).toBe(28);
    expect(remainingDailyDeliveries(39, 30)).toBe(0);
    expect(deliveryTierRank("priority")).toBeLessThan(deliveryTierRank("standard"));
  });

  it("closes the quota exactly at the configured boundary", () => {
    expect(remainingDailyDeliveries(30, 30)).toBe(0);
    expect(remainingDailyDeliveries(100, 100)).toBe(0);
    expect(remainingDailyDeliveries(-1, 30)).toBe(30);
  });
});
