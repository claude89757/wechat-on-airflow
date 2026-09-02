import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createSubscription,
  DASHBOARD_CLIENT_CACHE_MS,
  EMPTY_DASHBOARD,
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

function dashboardFetchMock() {
  return vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => dashboardResponse());
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

  it("keeps automatic UI refreshes in memory for one day", async () => {
    const fetchMock = dashboardFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    expect(DASHBOARD_CLIENT_CACHE_MS).toBe(86_400_000);
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

  it("bypasses client and edge caches for an explicit manual refresh", async () => {
    const fetchMock = dashboardFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    await getDashboard(null);
    await getDashboard(null, { force: true });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1]?.[0]).toBe("/api/bootstrap?refresh=1");
    expect(fetchMock.mock.calls[1]?.[1]).toMatchObject({
      method: "GET",
      cache: "no-store",
    });
  });

  it("keeps fallback and empty venue totals aligned with the venue catalog", () => {
    expect(FALLBACK_DASHBOARD.metrics.totalVenues).toBe(FALLBACK_DASHBOARD.venues.length);
    expect(FALLBACK_DASHBOARD.metrics.healthyVenues).toBe(FALLBACK_DASHBOARD.venues.length);
    expect(EMPTY_DASHBOARD.metrics.totalVenues).toBe(EMPTY_DASHBOARD.venues.length);
  });

  it("coalesces concurrent refreshes for the same identity", async () => {
    const fetchMock = dashboardFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([getDashboard(null), getDashboard(null), getDashboard(null)]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("never shares a cached dashboard between identities", async () => {
    const fetchMock = dashboardFetchMock();
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
    const fetchMock = dashboardFetchMock();
    vi.stubGlobal("fetch", fetchMock);

    await getDashboard(null);
    invalidateDashboardCache();
    await getDashboard(null);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("subscription client", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    invalidateDashboardCache();
  });

  it("sends the selected ISO weekdays to the Worker", async () => {
    const receipt: VerificationReceipt = {
      token: "receipt-token",
      email: "person@example.com",
      maskedEmail: "p***@example.com",
      verifiedAt: "2026-08-27T02:00:00.000Z",
    };
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) =>
      new Response(JSON.stringify({
        subscription: {
          id: "subscription-id",
          venueIds: ["szw"],
          weekdays: [6, 7],
          startTime: "18:00",
          endTime: "22:00",
          durationDays: 7,
          termCode: "7d",
          autoRenew: false,
          eligible: true,
          activeUntil: "2026-09-03T02:00:00.000Z",
          active: true,
          createdAt: "2026-08-27T02:00:00.000Z",
        },
      }), { status: 201, headers: { "Content-Type": "application/json" } }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await createSubscription(receipt, {
      venueIds: ["szw"],
      weekdays: [6, 7],
      startTime: "18:00",
      endTime: "22:00",
      termCode: "7d",
    });

    expect(fetchMock).toHaveBeenCalledWith("/api/subscriptions", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({
        venueIds: ["szw"],
        weekdays: [6, 7],
        startTime: "18:00",
        endTime: "22:00",
        termCode: "7d",
      }),
      headers: expect.objectContaining({ Authorization: "Bearer receipt-token" }),
    }));
  });
});
