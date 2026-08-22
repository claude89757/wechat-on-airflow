import { describe, expect, it } from "vitest";

import {
  LONG_TERM_LEASE_DAYS,
  normalizeSubscriptionTerm,
  resolveSubscriptionTerm,
  subscriptionTermAllowed,
  subscriptionTermsForTier,
} from "./subscription-terms";

describe("subscription term policy", () => {
  it("keeps standard users within seven to fourteen days", () => {
    expect(subscriptionTermsForTier("standard")).toEqual([
      "7d",
      "8d",
      "9d",
      "10d",
      "11d",
      "12d",
      "13d",
      "14d",
    ]);
    expect(subscriptionTermAllowed("standard", "14d")).toBe(true);
    expect(subscriptionTermAllowed("standard", "30d")).toBe(false);
    expect(subscriptionTermAllowed("standard", "long_term")).toBe(false);
  });

  it("unlocks extended and long-term choices for priority users", () => {
    expect(subscriptionTermAllowed("priority", "30d")).toBe(true);
    expect(subscriptionTermAllowed("priority", "90d")).toBe(true);
    expect(subscriptionTermAllowed("priority", "180d")).toBe(true);
    expect(subscriptionTermAllowed("priority", "long_term")).toBe(true);
  });

  it("accepts the legacy durationDays contract during rollout", () => {
    expect(normalizeSubscriptionTerm(undefined, 7)).toBe("7d");
    expect(normalizeSubscriptionTerm(undefined, 14)).toBe("14d");
    expect(() => normalizeSubscriptionTerm(undefined, 15)).toThrow("订阅有效期无效");
  });

  it("uses a renewable bounded lease for long-term subscriptions", () => {
    const now = new Date("2026-08-23T00:00:00.000Z");
    const resolved = resolveSubscriptionTerm("long_term", now);
    expect(resolved).toEqual({
      termCode: "long_term",
      durationDays: 0,
      autoRenew: true,
      activeUntil: new Date(
        now.getTime() + LONG_TERM_LEASE_DAYS * 86_400_000,
      ).toISOString(),
    });
  });
});
