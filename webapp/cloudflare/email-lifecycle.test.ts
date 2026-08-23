import { describe, expect, it } from "vitest";
import {
  normalizeTencentDeliveryStatus,
  shouldEnqueueExpiryReminder,
} from "./email-lifecycle";

describe("email lifecycle", () => {
  it("does not call an accepted request delivered", () => {
    expect(normalizeTencentDeliveryStatus({ MessageId: "m1" }).state).toBe("submitted");
  });
  it("requires provider delivery evidence", () => {
    const status = normalizeTencentDeliveryStatus({
      MessageId: "m1",
      DeliverTime: "2026-08-23T01:00:00.000Z",
    });
    expect(status.state).toBe("delivered");
    expect(status.deliveredAt).toBe("2026-08-23T01:00:00.000Z");
  });
  it("recognizes provider failures", () => {
    expect(normalizeTencentDeliveryStatus({
      DeliverStatus: "failed",
      DeliverMessage: "mailbox unavailable",
    })).toMatchObject({ state: "failed", error: "mailbox unavailable" });
  });
  it("queues fixed subscriptions only in their final day", () => {
    const now = new Date("2026-08-23T00:00:00.000Z");
    expect(shouldEnqueueExpiryReminder("2026-08-23T20:00:00.000Z", now)).toBe(true);
    expect(shouldEnqueueExpiryReminder("2026-08-25T00:00:00.000Z", now)).toBe(false);
  });
});
