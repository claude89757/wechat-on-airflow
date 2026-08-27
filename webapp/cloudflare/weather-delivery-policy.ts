import type { DeliveryTier } from "./delivery-tiers";
import type { WeatherEmailGateDecision } from "./weather-email-gate";

export const PRIORITY_WEATHER_BYPASS_ENABLED = true;

export type TieredWeatherDelivery = {
  tier: DeliveryTier;
};

function precipitationSuppressionActive(
  decision: WeatherEmailGateDecision,
): boolean {
  return (
    !decision.sendEmail
    && decision.reason === "precipitation_threshold_met"
  );
}

export function weatherSuppressedForTier(
  decision: WeatherEmailGateDecision,
  tier: DeliveryTier,
): boolean {
  return precipitationSuppressionActive(decision) && tier === "standard";
}

export function partitionWeatherDeliveries<T extends TieredWeatherDelivery>(
  items: T[],
  decision: WeatherEmailGateDecision,
): {
  sendable: T[];
  suppressed: T[];
  priorityBypass: T[];
} {
  const sendable: T[] = [];
  const suppressed: T[] = [];
  const priorityBypass: T[] = [];
  for (const item of items) {
    if (weatherSuppressedForTier(decision, item.tier)) {
      suppressed.push(item);
      continue;
    }
    sendable.push(item);
    if (precipitationSuppressionActive(decision) && item.tier === "priority") {
      priorityBypass.push(item);
    }
  }
  return { sendable, suppressed, priorityBypass };
}
