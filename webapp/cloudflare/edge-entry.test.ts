import { describe, expect, it } from "vitest";

import { hostCoreCutoverEnabled, hostCoreOrigin } from "./edge-entry";

describe("Airflow-host edge gateway", () => {
  it("keeps cutover explicit and reversible", () => {
    expect(hostCoreCutoverEnabled(undefined)).toBe(false);
    expect(hostCoreCutoverEnabled("false")).toBe(false);
    expect(hostCoreCutoverEnabled("true")).toBe(true);
    expect(hostCoreCutoverEnabled("1")).toBe(true);
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
