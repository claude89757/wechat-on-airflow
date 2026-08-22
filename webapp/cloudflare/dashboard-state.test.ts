import { describe, expect, it } from "vitest";

import {
  resolveDashboardAvailability,
  resolveVenueDisplayState,
} from "../src/dashboard-state";

describe("dashboard availability", () => {
  it("does not report venue failures before the first successful bootstrap", () => {
    const availability = resolveDashboardAvailability({
      hasSuccessfulDashboard: false,
      loading: true,
      refreshFailed: false,
    });
    expect(availability).toBe("loading");
    expect(resolveVenueDisplayState(availability, false)).toBe("unknown");
  });

  it("keeps the last successful venue state after a refresh failure", () => {
    const availability = resolveDashboardAvailability({
      hasSuccessfulDashboard: true,
      loading: false,
      refreshFailed: true,
    });
    expect(availability).toBe("stale");
    expect(resolveVenueDisplayState(availability, true)).toBe("healthy");
    expect(resolveVenueDisplayState(availability, false)).toBe("unhealthy");
  });
});
