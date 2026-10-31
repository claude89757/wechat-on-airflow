import type { Weekday } from "./api";

export const IDEAL_WINDOW_PRESETS = [
  {
    id: "weekday_evening",
    label: "工作日晚间",
    preferenceLabel: "下班后打球",
    detail: "周一至周五",
    weekdays: [1, 2, 3, 4, 5] as Weekday[],
    startTime: "19:00",
    endTime: "22:00",
  },
  {
    id: "weekday_noon",
    label: "午休局",
    preferenceLabel: "午休局",
    detail: "周一至周五",
    weekdays: [1, 2, 3, 4, 5] as Weekday[],
    startTime: "12:00",
    endTime: "14:00",
  },
  {
    id: "weekend_morning",
    label: "周末上午",
    preferenceLabel: "周末上午",
    detail: "周六与周日",
    weekdays: [6, 7] as Weekday[],
    startTime: "08:00",
    endTime: "12:00",
  },
  {
    id: "weekend_afternoon",
    label: "周末下午",
    preferenceLabel: "周末下午",
    detail: "周六与周日",
    weekdays: [6, 7] as Weekday[],
    startTime: "14:00",
    endTime: "18:00",
  },
] as const;

export type NamedIdealWindowId = (typeof IDEAL_WINDOW_PRESETS)[number]["id"];
export type IdealWindowPresetId = NamedIdealWindowId | "custom";
export type IdealWindowPreset = (typeof IDEAL_WINDOW_PRESETS)[number];

export const DEFAULT_IDEAL_WINDOW = IDEAL_WINDOW_PRESETS[0];

export function describeIdealWindow(
  weekdays: readonly number[],
  startTime: string,
  endTime: string,
): { id: IdealWindowPresetId; label: string } {
  const key = [...weekdays].sort((left, right) => left - right).join(",");
  const match = IDEAL_WINDOW_PRESETS.find(
    (preset) => preset.weekdays.join(",") === key
      && preset.startTime === startTime
      && preset.endTime === endTime,
  );
  return match
    ? { id: match.id, label: match.preferenceLabel }
    : { id: "custom", label: "自定义" };
}
