import type { DeliveryTier } from "./delivery-tiers";

export const STANDARD_SUBSCRIPTION_TERMS = [
  "7d", "8d", "9d", "10d", "11d", "12d", "13d", "14d",
] as const;
export const PRIORITY_EXTRA_SUBSCRIPTION_TERMS = [
  "30d", "90d", "180d", "long_term",
] as const;
export const PRIORITY_SUBSCRIPTION_TERMS = [
  ...STANDARD_SUBSCRIPTION_TERMS,
  ...PRIORITY_EXTRA_SUBSCRIPTION_TERMS,
] as const;

export type StandardSubscriptionTerm = (typeof STANDARD_SUBSCRIPTION_TERMS)[number];
export type PriorityExtraSubscriptionTerm =
  (typeof PRIORITY_EXTRA_SUBSCRIPTION_TERMS)[number];
export type SubscriptionTerm = StandardSubscriptionTerm | PriorityExtraSubscriptionTerm;

export const LONG_TERM_LEASE_DAYS = 90;
export const LONG_TERM_RENEW_THRESHOLD_DAYS = 45;

const DAY_MS = 86_400_000;
const ALL_TERMS = new Set<string>(PRIORITY_SUBSCRIPTION_TERMS);
const STANDARD_TERMS = new Set<string>(STANDARD_SUBSCRIPTION_TERMS);
const FIXED_TERM_DAYS: Record<Exclude<SubscriptionTerm, "long_term">, number> = {
  "7d": 7,
  "8d": 8,
  "9d": 9,
  "10d": 10,
  "11d": 11,
  "12d": 12,
  "13d": 13,
  "14d": 14,
  "30d": 30,
  "90d": 90,
  "180d": 180,
};

export type ResolvedSubscriptionTerm = {
  termCode: SubscriptionTerm;
  durationDays: number;
  autoRenew: boolean;
  activeUntil: string;
};

export function normalizeSubscriptionTerm(
  value: unknown,
  legacyDurationDays?: unknown,
): SubscriptionTerm {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (ALL_TERMS.has(normalized)) return normalized as SubscriptionTerm;
  const legacyDays = Number(legacyDurationDays);
  if (Number.isInteger(legacyDays) && legacyDays >= 7 && legacyDays <= 14) {
    return `${legacyDays}d` as StandardSubscriptionTerm;
  }
  throw new Error("订阅有效期无效");
}

export function subscriptionTermAllowed(
  tier: DeliveryTier,
  term: SubscriptionTerm,
): boolean {
  return tier === "priority" || STANDARD_TERMS.has(term);
}

export function subscriptionTermsForTier(tier: DeliveryTier): SubscriptionTerm[] {
  return tier === "priority"
    ? [...PRIORITY_SUBSCRIPTION_TERMS]
    : [...STANDARD_SUBSCRIPTION_TERMS];
}

export function resolveSubscriptionTerm(
  term: SubscriptionTerm,
  now = new Date(),
): ResolvedSubscriptionTerm {
  const autoRenew = term === "long_term";
  const durationDays = autoRenew ? 0 : FIXED_TERM_DAYS[term];
  const leaseDays = autoRenew ? LONG_TERM_LEASE_DAYS : durationDays;
  return {
    termCode: term,
    durationDays,
    autoRenew,
    activeUntil: new Date(now.getTime() + leaseDays * DAY_MS).toISOString(),
  };
}
