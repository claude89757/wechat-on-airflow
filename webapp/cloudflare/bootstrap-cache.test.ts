import { describe, expect, it } from "vitest";

import {
  BOOTSTRAP_CACHE_TTL_SECONDS,
  bootstrapCacheRequest,
} from "./bootstrap-cache";

describe("bootstrap edge cache", () => {
  it("uses a short bounded freshness window", () => {
    expect(BOOTSTRAP_CACHE_TTL_SECONDS).toBe(120);
  });

  it("separates anonymous and verified dashboard payloads", async () => {
    const anonymous = await bootstrapCacheRequest(null, "pepper");
    const verified = await bootstrapCacheRequest("receipt-token", "pepper");
    expect(anonymous.url).not.toBe(verified.url);
  });

  it("never exposes a receipt token in the synthetic cache URL", async () => {
    const token = "secret-receipt-token";
    const key = await bootstrapCacheRequest(token, "pepper");
    expect(key.url).not.toContain(token);
    expect(key.url).toMatch(/^https:\/\/bootstrap-cache\.invalid\/v1\/[0-9a-f]{64}$/);
  });
});
