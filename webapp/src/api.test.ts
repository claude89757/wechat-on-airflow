import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  DASHBOARD_CLIENT_CACHE_MS,
  FALLBACK_DASHBOARD,
  getDashboard,
  invalidateDashboardCache,
  type VerificationReceipt,
} from "./api";

function dashboardResponse(): Response {
  return new Response(JSON.stringify(FALLBACK_DASHBOARD), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("dashboard client cache", () => {
  beforeEach(() => {
    invalidateDashboardCache();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-08-27T02:00:00.000Z"));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    invalidateDashboardCache();
  });

  it("turns the 30-second UI refresh loop into one network request per two minutes", async () => {
    const fetchMock = vi.fn().mockResolvedValue(dashboardResponse());
    vi.stubGlobal("fetch", fetchMock);

    await getDashboard(null);
    vi.advanceTimersByTime(30_000);
    await getDashboard(null);
    vi.advanceTimersByTime(DASHBOARD_CLIENT_CACHE_MS - 30_001);
    await getDashboard(null);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(1);
    await getDashboard(null);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("coalesces concurrent refreshes for the same identity", async () => {
    const fetchMock = vi.fn().mockResolvedValue(dashboardResponse());
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([getDashboard(null), getDashboard(null), getDashboard(null)]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("never shares a cached dashboard between identities", async () => {
    const fetchMock = vi.fn().mockResolvedValue(dashboardResponse());
    vi.stubGlobal("fetch", fetchMock);
    const receipt: VerificationReceipt = {
      token: "receipt-token",
      email: "person@example.com",
      maskedEmail: "p***@example.com",
      verifiedAt: "2026-08-27T02:00:00.000Z",
    };

    await getDashboard(null);
    await getDashboard(receipt);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      headers: expect.objectContaining({ Authorization: "Bearer receipt-token" }),
    });
  });

  it("supports immediate refresh after a state-changing action", async () => {
    const fetchMock = vi.fn().mockResolvedValue(dashboardResponse());
    vi.stubGlobal("fetch", fetchMock);

    await getDashboard(null);
    invalidateDashboardCache();
    await getDashboard(null);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
