import { describe, expect, it } from "vitest";

import {
  alternativeIdealWindowPresets,
  describeIdealWindow,
  IDEAL_WINDOW_PRESETS,
} from "./ideal-windows";

describe("ideal window presets", () => {
  it("keeps the canonical single-window mapping used by the host API", () => {
    expect(IDEAL_WINDOW_PRESETS.map((preset) => [
      preset.id,
      preset.weekdays.join(","),
      preset.startTime,
      preset.endTime,
    ])).toEqual([
      ["weekday_evening", "1,2,3,4,5", "19:00", "22:00"],
      ["weekday_noon", "1,2,3,4,5", "12:00", "14:00"],
      ["weekend_morning", "6,7", "08:00", "12:00"],
      ["weekend_afternoon", "6,7", "14:00", "18:00"],
    ]);
  });

  it("uses the button label as the stored preference label", () => {
    for (const preset of IDEAL_WINDOW_PRESETS) {
      expect(describeIdealWindow(preset.weekdays, preset.startTime, preset.endTime)).toEqual({
        id: preset.id,
        label: preset.label,
      });
    }
    expect(IDEAL_WINDOW_PRESETS[0]?.label).toBe("工作日晚间");
  });

  it("offers the other named presets and keeps a custom window on all four", () => {
    expect(alternativeIdealWindowPresets([1, 2, 3, 4, 5], "19:00", "22:00").map((preset) => preset.id))
      .toEqual(["weekday_noon", "weekend_morning", "weekend_afternoon"]);
    expect(alternativeIdealWindowPresets([6, 7], "08:00", "12:00").map((preset) => preset.id))
      .not.toContain("weekend_morning");
    expect(alternativeIdealWindowPresets([1, 2, 3, 4, 5, 6, 7], "18:00", "22:00").map((preset) => preset.id))
      .toEqual(IDEAL_WINDOW_PRESETS.map((preset) => preset.id));
  });

  it("labels an exact stored window and leaves historical windows custom", () => {
    expect(describeIdealWindow([5, 1, 4, 2, 3], "19:00", "22:00")).toEqual({
      id: "weekday_evening",
      label: "工作日晚间",
    });
    expect(describeIdealWindow([1, 2, 3, 4, 5, 6, 7], "18:00", "22:00")).toEqual({
      id: "custom",
      label: "自定义",
    });
  });
});
