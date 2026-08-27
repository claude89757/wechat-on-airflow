import { describe, expect, it } from "vitest";

import {
  partitionWeatherDeliveries,
  weatherSuppressedForTier,
} from "./weather-delivery-policy";
import type { WeatherEmailGateDecision } from "./weather-email-gate";

const HEAVY_RAIN: WeatherEmailGateDecision = {
  sendEmail: false,
  reason: "precipitation_threshold_met",
  forecastDate: "2026-08-27",
  precipitationMm: 32,
  thresholdMm: 25,
  error: null,
};

describe("tier-aware weather delivery policy", () => {
  it("suppresses standard users but lets priority users bypass heavy rain", () => {
    const standard = { id: "standard", tier: "standard" as const };
    const priority = { id: "priority", tier: "priority" as const };
    const result = partitionWeatherDeliveries([standard, priority], HEAVY_RAIN);

    expect(result.suppressed).toEqual([standard]);
    expect(result.sendable).toEqual([priority]);
    expect(result.priorityBypass).toEqual([priority]);
    expect(weatherSuppressedForTier(HEAVY_RAIN, "standard")).toBe(true);
    expect(weatherSuppressedForTier(HEAVY_RAIN, "priority")).toBe(false);
  });

  it("sends both tiers below the threshold", () => {
    const result = partitionWeatherDeliveries([
      { id: "standard", tier: "standard" as const },
      { id: "priority", tier: "priority" as const },
    ], {
      ...HEAVY_RAIN,
      sendEmail: true,
      reason: "precipitation_below_threshold",
      precipitationMm: 4,
    });
    expect(result.sendable).toHaveLength(2);
    expect(result.suppressed).toEqual([]);
    expect(result.priorityBypass).toEqual([]);
  });

  it("keeps weather-provider failures fail-open for both tiers", () => {
    const result = partitionWeatherDeliveries([
      { id: "standard", tier: "standard" as const },
      { id: "priority", tier: "priority" as const },
    ], {
      ...HEAVY_RAIN,
      sendEmail: true,
      reason: "weather_unavailable",
      precipitationMm: null,
      error: "timeout",
    });
    expect(result.sendable).toHaveLength(2);
    expect(result.suppressed).toEqual([]);
  });
});
