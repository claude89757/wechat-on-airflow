import { describe, expect, it } from "vitest";

import {
  ALL_WEEKDAY_MASK,
  bookingDateWeekday,
  formatNotificationDigest,
  activeUntilIso,
  formatSlotLine,
  maskEmail,
  normalizeEmail,
  slotMatchesTimeRange,
  slotMatchesWeekday,
  validateSlotObservation,
  validateSubscriptionInput,
  weekdayMaskFromDays,
  weekdaysFromMask,
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

  it("defaults legacy clients to every weekday and validates explicit selections", () => {
    expect(validateSubscriptionInput({
      venueIds: ["szw"],
      startTime: "18:00",
      endTime: "20:00",
      durationDays: 7,
    }).weekdays).toEqual([1, 2, 3, 4, 5, 6, 7]);

    expect(validateSubscriptionInput({
      venueIds: ["szw"],
      weekdays: [7, 6, 6],
      startTime: "18:00",
      endTime: "20:00",
      durationDays: 7,
    }).weekdays).toEqual([6, 7]);

    expect(() => validateSubscriptionInput({
      venueIds: ["szw"],
      weekdays: [],
      startTime: "18:00",
      endTime: "20:00",
      durationDays: 7,
    })).toThrow("至少选择一个星期");

    expect(() => validateSubscriptionInput({
      venueIds: ["szw"],
      weekdays: [8],
      startTime: "18:00",
      endTime: "20:00",
      durationDays: 7,
    })).toThrow("星期选择无效");
  });

  it("round-trips weekday masks and matches the booking date", () => {
    const weekendMask = weekdayMaskFromDays([6, 7]);
    expect(weekendMask).toBe(96);
    expect(weekdaysFromMask(weekendMask)).toEqual([6, 7]);
    expect(weekdaysFromMask(null)).toEqual([1, 2, 3, 4, 5, 6, 7]);
    expect(weekdayMaskFromDays([1, 2, 3, 4, 5, 6, 7])).toBe(ALL_WEEKDAY_MASK);
    expect(bookingDateWeekday("2026-08-29")).toBe(6);

    const saturday = validateSlotObservation({
      date: "2026-08-29",
      court_name: "1号场",
      start_time: "18:00",
      end_time: "19:00",
    });
    const monday = validateSlotObservation({
      date: "2026-08-31",
      court_name: "1号场",
      start_time: "18:00",
      end_time: "19:00",
    });
    expect(slotMatchesWeekday(saturday, weekendMask)).toBe(true);
    expect(slotMatchesWeekday(monday, weekendMask)).toBe(false);
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

  it("accepts Fansibote chain-court subscriptions", () => {
    expect(
      validateSubscriptionInput({
        venueIds: ["fsb_shenyun", "fsb_shekou", "fsb_xinan", "fsb_zhengzhong", "fsb_atuoshan"],
        startTime: "18:00",
        endTime: "22:00",
        durationDays: 7,
      }).venueIds,
    ).toEqual(["fsb_shenyun", "fsb_shekou", "fsb_xinan", "fsb_zhengzhong", "fsb_atuoshan"]);
  });

  it("accepts PICKLE POP Bao'an subscriptions", () => {
    expect(
      validateSubscriptionInput({
        venueIds: ["ppba"],
        startTime: "18:00",
        endTime: "22:00",
        durationDays: 7,
      }).venueIds,
    ).toEqual(["ppba"]);
  });

  it("registers fifteen venues including Fansibote chain courts", () => {
    expect(Object.keys(VENUES)).toHaveLength(15);
    expect(VENUES.ppba).toBe("PICKLE POP宝安");
    expect(VENUES.dsh).toBe("大沙河国际网球中心");
    expect(VENUES.fsb_shenyun).toBe("泛思博特深云");
    expect(VENUES.fsb_shekou).toBe("泛思博特蛇口");
    expect(VENUES.fsb_xinan).toBe("泛思博特新安");
    expect(VENUES.fsb_zhengzhong).toBe("泛思博特正中");
    expect(VENUES.fsb_atuoshan).toBe("泛思博特安托山");
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
