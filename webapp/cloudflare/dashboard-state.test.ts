import { describe, expect, it } from "vitest";
import {
  resolveDashboardAvailability,
  resolveVenueDisplayState,
  type DashboardAvailability,
} from "../src/dashboard-state";

describe("dashboard availability", () => {
  it("does not report failures before the first successful bootstrap", () => {
    const availability = resolveDashboardAvailability({
      hasSuccessfulDashboard: false, loading: true, refreshFailed: false,
    });
    expect(availability).toBe("loading");
    expect(resolveVenueDisplayState(availability, false)).toBe("unknown");
  });
  it("retains the snapshot but does not certify cached health after a failed refresh", () => {
    const availability = resolveDashboardAvailability({
      hasSuccessfulDashboard: true, loading: false, refreshFailed: true,
    });
    expect(availability).toBe("stale");
    expect(resolveVenueDisplayState(availability, true)).toBe("unknown");
    expect(resolveVenueDisplayState(availability, false)).toBe("unknown");
  });
  it.each(["loading", "unknown", "stale"] as DashboardAvailability[])(
    "cannot present %s data as a current success or failure", availability => {
      expect(resolveVenueDisplayState(availability, true)).toBe("unknown");
      expect(resolveVenueDisplayState(availability, false)).toBe("unknown");
    },
  );
  it("restores the live venue state only after a successful refresh", () => {
    const availability = resolveDashboardAvailability({
      hasSuccessfulDashboard: true, loading: false, refreshFailed: false,
    });
    expect(availability).toBe("ready");
    expect(resolveVenueDisplayState(availability, true)).toBe("healthy");
    expect(resolveVenueDisplayState(availability, false)).toBe("unhealthy");
  });
});
