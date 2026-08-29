import { describe, expect, it } from "vitest";

import {
  formatNotificationDigest,
  activeUntilIso,
  formatSlotLine,
  maskEmail,
  normalizeEmail,
  slotMatchesTimeRange,
  validateSlotObservation,
  validateSubscriptionInput,
  VENUES,
} from "./domain";

describe("subscription domain", () => {
  it("normalizes and masks a verified email", () => {
    expect(normalizeEmail("  Person@Example.com ")).toBe("person@example.com");
    expect(maskEmail("person@example.com")).toBe("pe****@example.com");
  });

  it("rejects invalid subscription windows and durations", () => {
    expect(() =>
      validateSubscriptionInput({
        venueIds: ["szw"],
        startTime: "20:00",
        endTime: "18:00",
        durationDays: 7,
      }),
    ).toThrow("结束时间");
    expect(() =>
      validateSubscriptionInput({
        venueIds: ["szw"],
        startTime: "18:00",
        endTime: "20:00",
        durationDays: 15,
      }),
    ).toThrow("7–14");
  });

  it("accepts Greater Bay Area subscriptions", () => {
    expect(
      validateSubscriptionInput({
        venueIds: ["gba"],
        startTime: "18:00",
        endTime: "21:00",
        durationDays: 7,
      }).venueIds,
    ).toEqual(["gba"]);
  });

  it("accepts Fansibote Fuzhongfu subscriptions", () => {
    expect(
      validateSubscriptionInput({
        venueIds: ["fsb"],
        startTime: "18:00",
        endTime: "22:00",
        durationDays: 7,
      }).venueIds,
    ).toEqual(["fsb"]);
  });

  it("registers nine venues including Dashah International Tennis Center", () => {
    expect(Object.keys(VENUES)).toHaveLength(9);
    expect(VENUES.dsh).toBe("大沙河国际网球中心");
  });

  it("accepts Dashah International Tennis Center subscriptions", () => {
    expect(
      validateSubscriptionInput({
        venueIds: ["dsh"],
        startTime: "18:00",
        endTime: "22:00",
        durationDays: 7,
      }).venueIds,
    ).toEqual(["dsh"]);
  });

  it("accepts Dashah River free-court subscriptions", () => {
    expect(
      validateSubscriptionInput({
        venueIds: ["dsh_free"],
        startTime: "08:00",
        endTime: "22:00",
        durationDays: 7,
      }).venueIds,
    ).toEqual(["dsh_free"]);
  });

  it("builds one concise email for multiple new slots", () => {
    expect(formatNotificationDigest([
      "大沙河免费场1号场 08-16 星期日 18:00-19:00",
      "大沙河免费场1号场 08-16 星期日 18:00-19:00",
      "大沙河免费场1号场 08-16 星期日 19:00-20:00",
      "大沙河免费场2号场 08-16 星期日 20:00-21:00",
    ])).toEqual({
      subject: "大沙河免费场1号场 08-16 星期日 18:00-20:00 等 2 个时段",
      body: "大沙河免费场1号场 08-16 星期日 18:00-20:00\n大沙河免费场2号场 08-16 星期日 20:00-21:00",
    });
  });

  it("matches overlapping slots but excludes touching boundaries", () => {
    const slot = validateSlotObservation({
      date: "2026-07-31",
      court_name: "1号场",
      start_time: "18:00",
      end_time: "19:00",
    });

    expect(slotMatchesTimeRange(slot, "18:30", "20:00")).toBe(true);
    expect(slotMatchesTimeRange(slot, "19:00", "20:00")).toBe(false);
    expect(slotMatchesTimeRange(slot, "17:00", "18:00")).toBe(false);
  });

  it("rejects impossible booking dates", () => {
    expect(() =>
      validateSlotObservation({
        date: "2026-02-30",
        court_name: "1号场",
        start_time: "18:00",
        end_time: "19:00",
      }),
    ).toThrow("场地数据无效");
  });

  it("formats a concise notification and exact validity period", () => {
    const slot = validateSlotObservation({
      date: "2026-07-31",
      court_name: "1号场",
      start_time: "18:00",
      end_time: "19:00",
    });

    expect(formatSlotLine("深圳湾", slot)).toBe(
      "深圳湾1号场 07-31 星期五 18:00-19:00",
    );
    expect(activeUntilIso(7, new Date("2026-07-29T00:00:00.000Z"))).toBe(
      "2026-08-05T00:00:00.000Z",
    );
  });
});
