import {afterEach, describe, expect, it, vi} from "vitest";
import edge, {edgeDeploymentHealth, hostCoreOrigin, originRequest} from "./edge-entry";
afterEach(() => vi.unstubAllGlobals());
const env = {DEPLOYMENT_COMMIT: "a".repeat(40), AIRFLOW_PUSH_TOKEN: "test-token"} as never;
describe("Host Core only gateway", () => {
  it("rejects insecure origin", () => {
    expect(hostCoreOrigin(undefined).toString()).toBe("https://airflow.claude89757.cc/zacks-api");
    expect(() => hostCoreOrigin("http://localhost")).toThrow("must use HTTPS");
  });
  it("reports actual host-only mode", () => {
    expect(edgeDeploymentHealth(env)).toMatchObject({cutover: true, migrationEndpoint: false, legacyRuntime: false, durableBusinessState: "none"});
  });
  it("never routes public internal or migration endpoints", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const response = await edge.fetch(new Request("https://example.test/api/internal/host-secret-envelope", {method: "POST"}), env);
    expect(response.status).toBe(404); expect(fetch).not.toHaveBeenCalled();
  });
  it("replaces spoofable trust headers and preserves user identity", () => {
    const outgoing = originRequest(new Request("https://example.test/api/bootstrap", {headers: {
      "Authorization": "Bearer test-receipt", "X-Zacks-Edge-Token": "spoof", "X-Zacks-Client-IP": "spoof", "CF-Connecting-IP": "192.0.2.1",
    }}), env);
    expect(outgoing.headers.get("Authorization")).toBe("Bearer test-receipt");
    expect(outgoing.headers.get("X-Zacks-Edge-Token")).toBe("test-token");
    expect(outgoing.headers.get("X-Zacks-Client-IP")).toBe("192.0.2.1");
  });
  it("origin outage returns 503 and never falls back to D1", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    expect((await edge.fetch(new Request("https://example.test/api/bootstrap"), env)).status).toBe(503);
  });
});
