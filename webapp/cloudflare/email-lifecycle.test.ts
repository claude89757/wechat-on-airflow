import { describe, expect, it } from "vitest";
import {
  normalizeTencentDeliveryStatus,
  shouldEnqueueExpiryReminder,
} from "./email-lifecycle";

describe("email lifecycle", () => {
  it("keeps Tencent accepted queue status pending", () => {
    expect(normalizeTencentDeliveryStatus({
      MessageId: "m1",
      SendStatus: 0,
      DeliverStatus: 0,
      DeliverTime: "2026-08-23T01:00:00.000Z",
    })).toMatchObject({ state: "submitted", deliveredAt: null });
  });

  it("maps Tencent numeric delivery success to delivered", () => {
    const status = normalizeTencentDeliveryStatus({
      MessageId: "m1",
      SendStatus: 0,
      DeliverStatus: 1,
      DeliverTime: "2026-08-23T01:00:00.000Z",
    });
    expect(status.state).toBe("delivered");
    expect(status.deliveredAt).toBe("2026-08-23T01:00:00.000Z");
  });

  it("keeps Tencent delayed delivery pending even with a reason", () => {
    expect(normalizeTencentDeliveryStatus({
      MessageId: "m1",
      SendStatus: 0,
      DeliverStatus: 8,
      DeliverMessage: "recipient server temporarily delayed the message",
    })).toMatchObject({ state: "submitted", error: null });
  });

  it.each([2, 3])("maps Tencent terminal delivery status %s to failed", (code) => {
    expect(normalizeTencentDeliveryStatus({
      MessageId: "m1",
      SendStatus: 0,
      DeliverStatus: code,
      DeliverMessage: "mailbox unavailable",
    })).toMatchObject({ state: "failed", error: "mailbox unavailable" });
  });

  it("maps non-zero Tencent processing status to failed", () => {
    expect(normalizeTencentDeliveryStatus({
      MessageId: "m1",
      SendStatus: 1007,
      DeliverStatus: 0,
    })).toMatchObject({ state: "failed" });
  });

  it("accepts DeliverTime as compatibility evidence only when status is absent", () => {
    const status = normalizeTencentDeliveryStatus({
      MessageId: "m1",
      DeliverTime: "2026-08-23T01:00:00.000Z",
    });
    expect(status.state).toBe("delivered");
    expect(status.deliveredAt).toBe("2026-08-23T01:00:00.000Z");
  });

  it("recognizes textual provider failures", () => {
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
