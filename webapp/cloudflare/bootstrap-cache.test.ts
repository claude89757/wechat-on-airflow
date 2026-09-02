import { describe, expect, it } from "vitest";

import {
  BOOTSTRAP_CACHE_RETENTION_SECONDS,
  BOOTSTRAP_CACHE_TTL_SECONDS,
  bootstrapCacheAgeSeconds,
  bootstrapCacheRequest,
} from "./bootstrap-cache";

const requestUrl = "https://zacks.claude89757.cc/api/bootstrap?ignored=1";

describe("bootstrap edge cache", () => {
  it("keeps a five-minute freshness window and a two-day recovery copy", () => {
    expect(BOOTSTRAP_CACHE_TTL_SECONDS).toBe(300);
    expect(BOOTSTRAP_CACHE_RETENTION_SECONDS).toBe(172_800);
  });

  it("classifies cache age from the stored-at marker", () => {
    const response = new Response("{}", {
      headers: { "X-Zacks-Bootstrap-Stored-At": "2026-09-02T00:00:00.000Z" },
    });
    expect(bootstrapCacheAgeSeconds(response, Date.parse("2026-09-02T00:04:59.000Z"))).toBe(299);
    expect(bootstrapCacheAgeSeconds(response, Date.parse("2026-09-02T00:06:00.000Z"))).toBe(360);
  });

  it("separates anonymous and verified dashboard payloads", async () => {
    const anonymous = await bootstrapCacheRequest(requestUrl, null, "pepper");
    const verified = await bootstrapCacheRequest(
      requestUrl,
      "receipt-token",
      "pepper",
    );
    expect(anonymous.url).not.toBe(verified.url);
  });

  it("never exposes a receipt token in the cache URL", async () => {
    const token = "secret-receipt-token";
    const key = await bootstrapCacheRequest(requestUrl, token, "pepper");
    expect(key.url).not.toContain(token);
    expect(key.url).toMatch(
      /^https:\/\/zacks\.claude89757\.cc\/__zacks_edge_cache\/bootstrap\/[0-9a-f]{64}$/,
    );
  });

  it("keeps the cache key inside the Worker custom-domain zone", async () => {
    const key = await bootstrapCacheRequest(requestUrl, null, "pepper");
    expect(new URL(key.url).origin).toBe("https://zacks.claude89757.cc");
    expect(new URL(key.url).search).toBe("");
  });
});
