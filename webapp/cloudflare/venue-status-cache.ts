import type { Dashboard, VenueStatus } from "../src/api";
import {
  deliveryTierLimits,
  type DeliveryTierEnv,
} from "./delivery-tiers";
import { VENUES, type VenueId } from "./domain";
import { freeTierObservationEnvelope } from "./free-tier-observation";
import { subscriptionTermsForTier } from "./subscription-terms";

const VENUE_STATUS_SNAPSHOT_VERSION = 1;

export type VenueStatusSnapshot = {
  version: typeof VENUE_STATUS_SNAPSHOT_VERSION;
  fingerprint: string;
  venueId: VenueId;
  venueName: string;
  healthy: boolean;
  checkedAt: string;
  observationScope: string;
  slotCount: number;
  hasError: boolean;
  storedAt: string;
};

type SnapshotDashboardEnv = DeliveryTierEnv & {
  STANDARD_ACTIVE_SUBSCRIPTION_LIMIT?: string;
  PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT?: string;
};

function configuredPositiveInteger(
  value: string | undefined,
  fallback: number,
): number {
  if (!value?.trim()) return fallback;
  const candidate = Number(value);
  return Number.isInteger(candidate) && candidate > 0 ? candidate : fallback;
}

export function isVenueStatusSnapshot(value: unknown): value is VenueStatusSnapshot {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Partial<VenueStatusSnapshot>;
  return Boolean(
    candidate.version === VENUE_STATUS_SNAPSHOT_VERSION
    && typeof candidate.fingerprint === "string"
    && /^[0-9a-f]{64}$/i.test(candidate.fingerprint)
    && typeof candidate.venueId === "string"
    && candidate.venueId in VENUES
    && candidate.venueName === VENUES[candidate.venueId as VenueId]
    && typeof candidate.healthy === "boolean"
    && typeof candidate.checkedAt === "string"
    && Number.isFinite(Date.parse(candidate.checkedAt))
    && typeof candidate.observationScope === "string"
    && candidate.observationScope.length > 0
    && candidate.observationScope.length <= 120
    && typeof candidate.slotCount === "number"
    && Number.isInteger(candidate.slotCount)
    && candidate.slotCount >= 0
    && typeof candidate.hasError === "boolean"
    && typeof candidate.storedAt === "string"
    && Number.isFinite(Date.parse(candidate.storedAt))
  );
}

export async function venueStatusSnapshotFromObservation(
  payload: unknown,
  now = Date.now(),
): Promise<VenueStatusSnapshot | null> {
  const envelope = await freeTierObservationEnvelope(payload, now);
  if (!envelope) return null;
  return {
    version: VENUE_STATUS_SNAPSHOT_VERSION,
    fingerprint: envelope.snapshot.fingerprint,
    venueId: envelope.venueId,
    venueName: envelope.venueName,
    healthy: envelope.healthy,
    checkedAt: envelope.checkedAt,
    observationScope: envelope.snapshot.observationScope,
    slotCount: envelope.snapshot.slotCount,
    hasError: Boolean(envelope.error),
    storedAt: new Date(now).toISOString(),
  };
}

function nextUtcResetIso(now: Date): string {
  return new Date(Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + 1,
  )).toISOString();
}

export function degradedDashboardFromVenueSnapshots(
  snapshots: readonly VenueStatusSnapshot[],
  env: SnapshotDashboardEnv,
  hasLocalReceipt: boolean,
  now = new Date(),
): Dashboard | null {
  if (!snapshots.length) return null;

  const snapshotByVenue = new Map(snapshots.map((snapshot) => [
    snapshot.venueId,
    snapshot,
  ]));
  const venueIds = Object.keys(VENUES) as VenueId[];
  const venues: VenueStatus[] = venueIds.flatMap((venueId) => {
    const snapshot = snapshotByVenue.get(venueId);
    if (!snapshot) return [];
    return [{
      id: venueId,
      name: VENUES[venueId],
      healthy: snapshot.healthy,
      subscriberCount: 0,
      lastInspectionAt: snapshot.checkedAt,
      lastNotificationAt: null,
    }];
  });
  const generatedAt = snapshots.reduce(
    (latest, snapshot) => snapshot.checkedAt > latest ? snapshot.checkedAt : latest,
    snapshots[0].checkedAt,
  );
  const tierLimits = deliveryTierLimits(env);
  const subscriptionLimits = {
    standard: configuredPositiveInteger(env.STANDARD_ACTIVE_SUBSCRIPTION_LIMIT, 5),
    priority: configuredPositiveInteger(env.PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT, 20),
  };
  const unavailableMetric = "—" as unknown as number;

  return {
    generatedAt,
    dataStatus: {
      stale: true,
      source: "edge-cache",
      reason: "data_store_unavailable",
      retryAt: nextUtcResetIso(now),
    },
    metrics: {
      activeSubscriptions: unavailableMetric,
      remindersToday: unavailableMetric,
      healthyVenues: snapshots.filter((snapshot) => snapshot.healthy).length,
      totalVenues: venueIds.length,
    },
    deliveryTiers: tierLimits,
    subscriptionTerms: {
      standard: subscriptionTermsForTier("standard"),
      priority: subscriptionTermsForTier("priority"),
    },
    subscriptionLimits,
    venues,
    identity: {
      verified: hasLocalReceipt,
      maskedEmail: hasLocalReceipt ? "本机已验证邮箱" : null,
      remindersToday: unavailableMetric,
      submittedToday: unavailableMetric,
      deliveredToday: unavailableMetric,
      failedToday: unavailableMetric,
      tier: "standard",
      isAdmin: false,
      dailyLimit: unavailableMetric,
      remainingToday: unavailableMetric,
      activeSubscriptionLimit: unavailableMetric,
      activeSubscriptionCount: unavailableMetric,
      remainingSubscriptions: unavailableMetric,
    },
    subscriptions: [],
  };
}
