import { describe, expect, it } from "vitest";

import {
  deliveryLimitForTier,
  deliveryTierLimits,
  deliveryTierRank,
  normalizeDeliveryTier,
  remainingDailyDeliveries,
} from "./delivery-tiers";

describe("subscriber email delivery tiers", () => {
  it("uses conservative configurable defaults", () => {
    expect(deliveryTierLimits({})).toEqual({ standard: 3, priority: 12 });
  });

  it("honors positive integer limits and never makes priority lower", () => {
    expect(deliveryTierLimits({
      STANDARD_DAILY_EMAIL_LIMIT: "5",
      PRIORITY_DAILY_EMAIL_LIMIT: "4",
    })).toEqual({ standard: 5, priority: 5 });
  });

  it("falls back for malformed limits", () => {
    expect(deliveryLimitForTier(
      {
        STANDARD_DAILY_EMAIL_LIMIT: "0",
        PRIORITY_DAILY_EMAIL_LIMIT: "not-a-number",
      },
      "priority",
    )).toBe(12);
  });

  it("normalizes unknown tiers to standard", () => {
    expect(normalizeDeliveryTier("priority")).toBe("priority");
    expect(normalizeDeliveryTier("vip")).toBe("standard");
  });

  it("computes remaining quota and prioritizes priority users", () => {
    expect(remainingDailyDeliveries(2, 3)).toBe(1);
    expect(remainingDailyDeliveries(9, 3)).toBe(0);
    expect(deliveryTierRank("priority")).toBeLessThan(deliveryTierRank("standard"));
  });
});
