import { describe, expect, it } from "vitest";

import {
  providerCheckError,
  reconciliationLanePlan,
  selectReconciliationCandidates,
} from "./delivery-reconcile";

describe("delivery reconciliation observability", () => {
  it("extracts a stable provider error code", () => {
    expect(providerCheckError(
      new Error("AuthFailure.UnauthorizedOperation: permission denied"),
    )).toEqual({
      code: "AuthFailure.UnauthorizedOperation",
      reason: "AuthFailure.UnauthorizedOperation: permission denied",
      status: "check_error:AuthFailure.UnauthorizedOperation",
    });
  });

  it("normalizes unexpected errors", () => {
    expect(providerCheckError("network unavailable")).toEqual({
      code: "unknown",
      reason: "unknown delivery status error",
      status: "check_error:unknown",
    });
  });
});

describe("delivery reconciliation lane selection", () => {
  it("reserves most capacity for recent messages while advancing backlog", () => {
    expect(reconciliationLanePlan(20)).toEqual({ recent: 16, backlog: 4 });
    expect(reconciliationLanePlan(1)).toEqual({ recent: 1, backlog: 0 });
  });

  it("selects current messages before the historical backlog", () => {
    const recent = Array.from({ length: 20 }, (_, index) => `recent-${index}`);
    const backlog = Array.from({ length: 20 }, (_, index) => `backlog-${index}`);
    const selected = selectReconciliationCandidates(recent, backlog, 20);

    expect(selected.recentCount).toBe(16);
    expect(selected.backlogCount).toBe(4);
    expect(selected.items).toEqual([
      ...recent.slice(0, 16),
      ...backlog.slice(0, 4),
    ]);
  });

  it("fills unused recent capacity from the queryable backlog", () => {
    const recent = ["recent-0", "recent-1"];
    const backlog = Array.from({ length: 10 }, (_, index) => `backlog-${index}`);
    const selected = selectReconciliationCandidates(recent, backlog, 5);

    expect(selected.recentCount).toBe(2);
    expect(selected.backlogCount).toBe(3);
    expect(selected.items).toEqual([
      "recent-0",
      "recent-1",
      "backlog-0",
      "backlog-1",
      "backlog-2",
    ]);
  });
});
