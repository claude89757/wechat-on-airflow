import { bootstrapFailureCanUseStale } from "./deployment-entry";
import { VENUES } from "./domain";
import worker from "./subscription-gated-entry";
import {
  degradedDashboardFromVenueSnapshots,
  isVenueStatusSnapshot,
  venueStatusSnapshotFromObservation,
  type VenueStatusSnapshot,
} from "./venue-status-cache";

export { VenueStatusObject } from "./venue-status-object";

type ResilientEnv = Env & {
  AIRFLOW_PUSH_TOKEN: string;
  VENUE_STATUS_STORE: DurableObjectNamespace;
  STANDARD_DAILY_EMAIL_LIMIT?: string;
  PRIORITY_DAILY_EMAIL_LIMIT?: string;
  STANDARD_ACTIVE_SUBSCRIPTION_LIMIT?: string;
  PRIORITY_ACTIVE_SUBSCRIPTION_LIMIT?: string;
};

function constantTimeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  if (leftBytes.byteLength !== rightBytes.byteLength) return false;
  let difference = 0;
  for (let index = 0; index < leftBytes.byteLength; index += 1) {
    difference |= leftBytes[index] ^ rightBytes[index];
  }
  return difference === 0;
}

function bearerToken(request: Request): string {
  const authorization = request.headers.get("authorization") || "";
  return authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
}

function authorizedObservationRequest(request: Request, env: ResilientEnv): boolean {
  const token = bearerToken(request);
  return Boolean(token) && constantTimeEqual(token, env.AIRFLOW_PUSH_TOKEN);
}

function jsonResponse(payload: unknown, status = 200): Response {
  return Response.json(payload, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function statusStore(env: ResilientEnv): DurableObjectStub {
  return env.VENUE_STATUS_STORE.get(env.VENUE_STATUS_STORE.idFromName("global"));
}

async function captureObservationSnapshot(
  request: Request,
  env: ResilientEnv,
): Promise<void> {
  if (!authorizedObservationRequest(request, env)) return;
  let payload: unknown;
  try {
    payload = await request.clone().json<unknown>();
  } catch {
    return;
  }
  const snapshot = await venueStatusSnapshotFromObservation(payload);
  if (!snapshot) return;
  try {
    const response = await statusStore(env).fetch(
      `https://venue-status.internal/snapshots/${snapshot.venueId}`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(snapshot),
      },
    );
    if (!response.ok) throw new Error(`status store returned HTTP ${response.status}`);
    console.log(JSON.stringify({
      event: "airflow_venue_status_snapshot_recorded",
      venueId: snapshot.venueId,
      observationScope: snapshot.observationScope,
      healthy: snapshot.healthy,
    }));
  } catch (error) {
    console.warn(JSON.stringify({
      event: "airflow_venue_status_snapshot_store_failed",
      venueId: snapshot.venueId,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  }
}

async function loadVenueStatusSnapshots(
  env: ResilientEnv,
): Promise<VenueStatusSnapshot[]> {
  const response = await statusStore(env).fetch("https://venue-status.internal/snapshots");
  if (!response.ok) return [];
  try {
    const payload = await response.json<{ snapshots?: unknown }>();
    return Array.isArray(payload.snapshots)
      ? payload.snapshots.filter(isVenueStatusSnapshot)
      : [];
  } catch {
    return [];
  }
}

function publicSnapshot(snapshot: VenueStatusSnapshot) {
  return {
    venueId: snapshot.venueId,
    venueName: snapshot.venueName,
    healthy: snapshot.healthy,
    checkedAt: snapshot.checkedAt,
    hasError: snapshot.hasError,
  };
}

async function venueStatusSnapshotResponse(env: ResilientEnv): Promise<Response> {
  const snapshots = await loadVenueStatusSnapshots(env);
  const latest = snapshots.reduce<string | null>(
    (current, snapshot) => !current || snapshot.checkedAt > current
      ? snapshot.checkedAt
      : current,
    null,
  );
  return jsonResponse({
    ok: snapshots.length > 0,
    source: "airflow-durable-status",
    generatedAt: latest,
    snapshotCount: snapshots.length,
    totalSnapshots: Object.keys(VENUES).length,
    venues: snapshots.map(publicSnapshot),
  }, snapshots.length ? 200 : 503);
}

async function observationDashboardFallback(
  request: Request,
  env: ResilientEnv,
): Promise<Response | null> {
  const snapshots = await loadVenueStatusSnapshots(env);
  const dashboard = degradedDashboardFromVenueSnapshots(
    snapshots,
    env,
    Boolean(bearerToken(request)),
  );
  if (!dashboard) return null;
  const response = jsonResponse(dashboard);
  response.headers.set("X-Zacks-Dashboard-Source", "airflow-durable-status");
  return response;
}

async function bootstrapFailureCanUseObservationFallback(
  response: Response,
): Promise<boolean> {
  try {
    return bootstrapFailureCanUseStale(response.status, await response.clone().text());
  } catch {
    return response.status >= 500;
  }
}

export default {
  async fetch(
    request: Request,
    env: ResilientEnv,
    context: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/venue-status-snapshot") {
      return venueStatusSnapshotResponse(env);
    }

    const observationRequest = request.method === "POST"
      && url.pathname === "/api/internal/observations";
    if (observationRequest) {
      await captureObservationSnapshot(request, env);
    }

    let response: Response;
    try {
      response = await worker.fetch(request, env as never, context);
    } catch (error) {
      if (request.method === "GET" && url.pathname === "/api/bootstrap") {
        const fallback = await observationDashboardFallback(request, env);
        if (fallback) return fallback;
      }
      throw error;
    }

    if (
      request.method === "GET"
      && url.pathname === "/api/bootstrap"
      && !response.ok
      && await bootstrapFailureCanUseObservationFallback(response)
    ) {
      const fallback = await observationDashboardFallback(request, env);
      if (fallback) return fallback;
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: ResilientEnv,
    context: ExecutionContext,
  ): Promise<void> {
    await worker.scheduled(controller, env as never, context);
  },
} satisfies ExportedHandler<ResilientEnv>;
