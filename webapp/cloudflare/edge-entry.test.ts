import { describe, expect, it } from "vitest";

import {
  edgeDeploymentHealth,
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

  it("reports edge identity without consulting D1 or the host origin", () => {
    expect(edgeDeploymentHealth({
      DEPLOYMENT_COMMIT: "a".repeat(40),
      HOST_CORE_CUTOVER: "true",
      HOST_CORE_QUIESCE: "false",
      HOST_CORE_MIGRATION_ENABLED: "false",
    } as never)).toEqual({
      ok: true,
      service: "zacks-tennis-edge",
      runtime: "cloudflare-stateless-edge",
      deploymentCommit: "a".repeat(40),
      cutover: true,
      quiesced: false,
      migrationEndpoint: false,
      durableBusinessState: "none",
    });
  });
});
