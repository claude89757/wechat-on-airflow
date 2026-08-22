import { describe, expect, it } from "vitest";

import { deploymentHealth } from "./deployment-entry";

describe("deployment entry health", () => {
  it("reports only an exact deployed commit", () => {
    const commit = "a".repeat(40);
    expect(deploymentHealth(commit)).toEqual({
      ok: true,
      service: "zacks-tennis-alerts",
      deploymentCommit: commit,
    });
    expect(deploymentHealth("main").deploymentCommit).toBe("unknown");
  });
});
