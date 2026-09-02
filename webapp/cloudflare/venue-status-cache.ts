import type { Dashboard, VenueStatus } from "../src/api";
import {
  deliveryTierLimits,
  type DeliveryTierEnv,
} from "./delivery-tiers";
import { VENUES, type VenueId } from "./domain";
import { freeTierObservationEnvelope } from "./free-tier-observation";
import { subscriptionTermsForTier } from "./subscription-terms";

const VENUE_STATUS_CACHE_VERSION = 1;
const VENUE_STATUS_CACHE_PREFIX = "/__zacks_edge_cache/venue-status";
export const VENUE_STATUS_CACHE_RETENTION_SECONDS = 365 * 24 * 60 * 60;

export type VenueStatusSnapshot = {
  version: typeof VENUE_STATUS_CACHE_VERSION;
  venueId: VenueId;
  venueName: string;
  healthy: boolean;
  checkedAt: string;
  observationScope: string;
  slotCount: number;
  hasError: boolean;
  storedAt: string;
};

export type VenueStatusCache = Pick<Cache, "match" | "put">;

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

function venueStatusCacheRequest(requestUrl: string, venueId: VenueId): Request {
  const url = new URL(requestUrl);
  url.pathname = `${VENUE_STATUS_CACHE_PREFIX}/${venueId}`;
  url.search = "";
  url.hash = "";
  return new Request(url.toString(), { method: "GET" });
}

function isVenueStatusSnapshot(value: unknown): value is VenueStatusSnapshot {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Partial<VenueStatusSnapshot>;
  if (
    candidate.version !== VENUE_STATUS_CACHE_VERSION
    || typeof candidate.venueId !== "string"
    || !(candidate.venueId in VENUES)
    || candidate.venueName !== VENUES[candidate.venueId as VenueId]
    || typeof candidate.healthy !== "boolean"
    || typeof candidate.checkedAt !== "string"
    || !Number.isFinite(Date.parse(candidate.checkedAt))
    || typeof candidate.observationScope !== "string"
    || typeof candidate.slotCount !== "number"
    || !Number.isInteger(candidate.slotCount)
    || candidate.slotCount < 0
    || typeof candidate.hasError !== "boolean"
    || typeof candidate.storedAt !== "string"
    || !Number.isFinite(Date.parse(candidate.storedAt))
  ) {
    return false;
  }
  return true;
}

export async function venueStatusSnapshotFromObservation(
  payload: unknown,
  now = Date.now(),
): Promise<VenueStatusSnapshot | null> {
  const envelope = await freeTierObservationEnvelope(payload, now);
  if (!envelope) return null;
  return {
    version: VENUE_STATUS_CACHE_VERSION,
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

export async function storeVenueStatusSnapshot(
  requestUrl: string,
  snapshot: VenueStatusSnapshot,
  cache: VenueStatusCache = caches.default,
): Promise<void> {
  const response = Response.json(snapshot, {
    headers: {
      "Cache-Control": `public, max-age=${VENUE_STATUS_CACHE_RETENTION_SECONDS}`,
      "Content-Type": "application/json; charset=utf-8",
      "X-Zacks-Cache-Kind": "airflow-venue-status",
    },
  });
  await cache.put(venueStatusCacheRequest(requestUrl, snapshot.venueId), response);
}

export async function loadVenueStatusSnapshot(
  requestUrl: string,
  venueId: VenueId,
  cache: VenueStatusCache = caches.default,
): Promise<VenueStatusSnapshot | null> {
  const response = await cache.match(venueStatusCacheRequest(requestUrl, venueId));
  if (!response) return null;
  try {
    const payload = await response.json<unknown>();
    return isVenueStatusSnapshot(payload) ? payload : null;
  } catch {
    return null;
  }
}

export async function loadVenueStatusSnapshots(
  requestUrl: string,
  cache: VenueStatusCache = caches.default,
): Promise<VenueStatusSnapshot[]> {
  const venueIds = Object.keys(VENUES) as VenueId[];
  const snapshots = await Promise.all(venueIds.map(async (venueId) => {
    try {
      return await loadVenueStatusSnapshot(requestUrl, venueId, cache);
    } catch {
      return null;
    }
  }));
  return snapshots.filter((snapshot): snapshot is VenueStatusSnapshot => Boolean(snapshot));
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
  now = new Date(),
): Dashboard | null {
  if (!snapshots.length) return null;

  const snapshotByVenue = new Map(snapshots.map((snapshot) => [
    snapshot.venueId,
    snapshot,
  ]));
  const venueIds = Object.keys(VENUES) as VenueId[];
  const venues: VenueStatus[] = venueIds.map((venueId) => {
    const snapshot = snapshotByVenue.get(venueId);
    return {
      id: venueId,
      name: VENUES[venueId],
      healthy: snapshot?.healthy ?? false,
      statusKnown: Boolean(snapshot),
      subscriberCount: 0,
      lastInspectionAt: snapshot?.checkedAt ?? null,
      lastNotificationAt: null,
    };
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

  return {
    generatedAt,
    dataStatus: {
      stale: true,
      partial: true,
      source: "observation-cache",
      reason: "data_store_unavailable",
      retryAt: nextUtcResetIso(now),
      snapshotCount: snapshots.length,
      totalSnapshots: venueIds.length,
    },
    metrics: {
      activeSubscriptions: 0,
      remindersToday: 0,
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
      verified: false,
      maskedEmail: null,
      remindersToday: 0,
      submittedToday: 0,
      deliveredToday: 0,
      failedToday: 0,
      tier: "standard",
      isAdmin: false,
      dailyLimit: tierLimits.standard,
      remainingToday: tierLimits.standard,
      activeSubscriptionLimit: subscriptionLimits.standard,
      activeSubscriptionCount: 0,
      remainingSubscriptions: subscriptionLimits.standard,
    },
    subscriptions: [],
  };
}
