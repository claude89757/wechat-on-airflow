import { describe, expect, it } from "vitest";

import {
  hostCoreCutoverEnabled,
  hostCoreMigrationEnabled,
  hostCoreOrigin,
  hostCoreQuiesceEnabled,
} from "./edge-entry";

describe("Airflow-host edge gateway", () => {
  it("keeps cutover, quiesce, and migration switches explicit", () => {
    expect(hostCoreCutoverEnabled(undefined)).toBe(false);
    expect(hostCoreCutoverEnabled("false")).toBe(false);
    expect(hostCoreCutoverEnabled("true")).toBe(true);
    expect(hostCoreCutoverEnabled("1")).toBe(true);
    expect(hostCoreQuiesceEnabled("yes")).toBe(true);
    expect(hostCoreQuiesceEnabled("off")).toBe(false);
    expect(hostCoreMigrationEnabled("on")).toBe(true);
    expect(hostCoreMigrationEnabled(undefined)).toBe(false);
  });

  it("accepts only an HTTPS host-core origin", () => {
    expect(hostCoreOrigin(undefined).toString()).toBe(
      "https://airflow.claude89757.cc/zacks-api",
    );
    expect(() => hostCoreOrigin("http://127.0.0.1:8090")).toThrow(
      "HOST_CORE_ORIGIN_URL must use HTTPS",
    );
  });
});
