export type DeliveryTier = "standard" | "priority";

export type DeliveryTierEnv = {
  STANDARD_DAILY_EMAIL_LIMIT?: string;
  PRIORITY_DAILY_EMAIL_LIMIT?: string;
};

export type DeliveryTierLimits = {
  standard: number;
  priority: number;
};

const DEFAULT_STANDARD_DAILY_EMAIL_LIMIT = 3;
const DEFAULT_PRIORITY_DAILY_EMAIL_LIMIT = 12;

function positiveInteger(value: string | undefined, fallback: number): number {
  if (value === undefined || value.trim() === "") return fallback;
  const candidate = Number(value);
  return Number.isInteger(candidate) && candidate > 0 ? candidate : fallback;
}

export function normalizeDeliveryTier(value: unknown): DeliveryTier {
  return value === "priority" ? "priority" : "standard";
}

export function deliveryTierLimits(env: DeliveryTierEnv): DeliveryTierLimits {
  const standard = positiveInteger(
    env.STANDARD_DAILY_EMAIL_LIMIT,
    DEFAULT_STANDARD_DAILY_EMAIL_LIMIT,
  );
  const configuredPriority = positiveInteger(
    env.PRIORITY_DAILY_EMAIL_LIMIT,
    DEFAULT_PRIORITY_DAILY_EMAIL_LIMIT,
  );
  return {
    standard,
    priority: Math.max(standard, configuredPriority),
  };
}

export function deliveryLimitForTier(
  env: DeliveryTierEnv,
  tier: DeliveryTier,
): number {
  return deliveryTierLimits(env)[tier];
}

export function remainingDailyDeliveries(sent: number, limit: number): number {
  return Math.max(0, limit - Math.max(0, Math.trunc(sent)));
}

export function deliveryTierRank(tier: DeliveryTier): number {
  return tier === "priority" ? 0 : 1;
}
