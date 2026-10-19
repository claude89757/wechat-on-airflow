import { describe, expect, it } from "vitest";

import {
  DEFAULT_INSPECTION_CADENCE_SECONDS,
  formatInspectionCadence,
  inspectionCadenceSeconds,
} from "../src/venue-inspection-display";

describe("venue inspection cadence display", () => {
  it("keeps the one-minute default for ordinary venues", () => {
    expect(DEFAULT_INSPECTION_CADENCE_SECONDS).toBe(60);
    expect(inspectionCadenceSeconds("tops")).toBe(60);
    expect(formatInspectionCadence("tops")).toBe("1分钟/次");
  });

  it.each(["szw", "gba"])(
    "shows the one-minute CRLand inspection cadence for %s",
    (venueId) => {
      expect(inspectionCadenceSeconds(venueId)).toBe(60);
      expect(formatInspectionCadence(venueId)).toBe("1分钟/次");
    },
  );

  it("shows the approved Dashah free-court low-latency exception", () => {
    expect(inspectionCadenceSeconds("dsh_free")).toBe(15);
    expect(formatInspectionCadence("dsh_free")).toBe("15秒/次");
  });

  it("shows the approved Dashah International exception", () => {
    expect(inspectionCadenceSeconds("dsh")).toBe(120);
    expect(formatInspectionCadence("dsh")).toBe("2分钟/次");
  });
});
