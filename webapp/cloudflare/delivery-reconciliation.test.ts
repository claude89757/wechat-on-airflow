import { describe, expect, it } from "vitest";

import { providerCheckError } from "./delivery-reconciliation";

describe("delivery reconciliation diagnostics", () => {
  it("extracts a stable Tencent API error code without exposing details in status", () => {
    expect(providerCheckError(
      new Error("AuthFailure.UnauthorizedOperation: permission denied for a sensitive resource"),
    )).toEqual({
      code: "AuthFailure.UnauthorizedOperation",
      reason: "AuthFailure.UnauthorizedOperation: permission denied for a sensitive resource",
      status: "check_error:AuthFailure.UnauthorizedOperation",
    });
  });

  it("normalizes unexpected errors to an operational code", () => {
    expect(providerCheckError("network disconnected")).toEqual({
      code: "unknown",
      reason: "unknown delivery status error",
      status: "check_error:unknown",
    });
  });
});
