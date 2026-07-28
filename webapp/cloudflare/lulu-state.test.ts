import { describe, expect, it } from "vitest";

import { resolveLuluState, type LuluSignals } from "../src/lulu";

const healthy: LuluSignals = {
  serviceOnline: true,
  healthyVenues: 5,
  totalVenues: 5,
  identityVerified: true,
  subscriptionCount: 1,
  remindersToday: 0,
  notificationBurst: false,
};

describe("Lulu state", () => {
  it("reflects verification, subscription, and reminder state", () => {
    expect(resolveLuluState({ ...healthy, identityVerified: false })).toBe(
      "welcoming",
    );
    expect(resolveLuluState({ ...healthy, subscriptionCount: 0 })).toBe("idle");
    expect(resolveLuluState(healthy)).toBe("watching");
    expect(resolveLuluState({ ...healthy, remindersToday: 1 })).toBe("happy");
    expect(resolveLuluState({ ...healthy, notificationBurst: true })).toBe(
      "celebrating",
    );
  });

  it("prioritizes service degradation over celebratory states", () => {
    expect(
      resolveLuluState({
        ...healthy,
        healthyVenues: 4,
        remindersToday: 1,
        notificationBurst: true,
      }),
    ).toBe("concerned");
    expect(resolveLuluState({ ...healthy, serviceOnline: false })).toBe(
      "concerned",
    );
  });
});
