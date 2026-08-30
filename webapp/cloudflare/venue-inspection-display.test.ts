import { describe, expect, it } from "vitest";

import {
  DEFAULT_INSPECTION_CADENCE_SECONDS,
  formatInspectionCadence,
  inspectionCadenceSeconds,
} from "../src/venue-inspection-display";

describe("venue inspection cadence display", () => {
  it("keeps the one-minute default for ordinary venues", () => {
    expect(DEFAULT_INSPECTION_CADENCE_SECONDS).toBe(60);
    expect(inspectionCadenceSeconds("gba")).toBe(60);
    expect(formatInspectionCadence("gba")).toBe("1分钟/次");
  });

  it("shows the approved Shenzhen Bay low-latency exception", () => {
    expect(inspectionCadenceSeconds("szw")).toBe(15);
    expect(formatInspectionCadence("szw")).toBe("15秒/次");
  });

  it("shows the resource-safe Dashah International exception", () => {
    expect(inspectionCadenceSeconds("dsh")).toBe(180);
    expect(formatInspectionCadence("dsh")).toBe("3分钟/次");
  });
});
