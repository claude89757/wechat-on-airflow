import { describe, expect, it } from "vitest";

import { providerCheckError } from "./delivery-reconcile";

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
