import worker from "./deployment-entry";
import {
  applyFreeTierObservationPolicy,
  type FreeTierObservationEnvelope,
} from "./free-tier-observation";
import { ensureFreeTierSchema } from "./free-tier-schema";
import {
  refreshWechatVenueGates,
  wechatGateForVenue,
} from "./wechat-subscription-gate";

type GateEnv = Env & {
  DB: D1Database;
  AIRFLOW_PUSH_TOKEN: string;
};

function observationVenueId(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const candidate = payload as Record<string, unknown>;
  const venueId = String(candidate.venue_id ?? candidate.venueId ?? "").trim();
  return venueId || null;
}

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

function authorizedObservationRequest(request: Request, env: GateEnv): boolean {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) return false;
  const token = authorization.slice(7).trim();
  return Boolean(token) && constantTimeEqual(token, env.AIRFLOW_PUSH_TOKEN);
}

async function enrichObservationResponse(
  response: Response,
  env: GateEnv,
  venueId: string,
): Promise<Response> {
  if (!response.ok) return response;
  try {
    const payload = await response.clone().json<Record<string, unknown>>();
    const gate = await wechatGateForVenue(env, venueId);
    const headers = new Headers(response.headers);
    headers.delete("Content-Length");
    headers.delete("Content-Encoding");
    headers.set("Cache-Control", "no-store");
    headers.set("Content-Type", "application/json; charset=utf-8");
    return new Response(JSON.stringify({ ...payload, wechatGate: gate }), {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  } catch (error) {
    console.warn(JSON.stringify({
      event: "wechat_subscription_gate_enrichment_failed",
      venueId,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
    return response;
  }
}

function gateMutation(method: string, pathname: string): boolean {
  return (
    (method === "POST" && pathname === "/api/subscriptions")
    || (method === "DELETE" && /^\/api\/subscriptions\/[0-9a-f-]{36}$/i.test(pathname))
    || (method === "POST" && pathname === "/api/priority/redeem")
    || (!["GET", "HEAD", "OPTIONS"].includes(method) && pathname.startsWith("/api/admin/"))
  );
}

function refreshSafely(env: GateEnv, source: string): Promise<void> {
  return refreshWechatVenueGates(env).catch((error) => {
    console.warn(JSON.stringify({
      event: "wechat_subscription_gate_refresh_failed",
      source,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  });
}

function invalidateObservationMatchingSafely(
  env: GateEnv,
  source: string,
): Promise<void> {
  const revision = `subscription-change:${Date.now()}`;
  return env.DB.prepare(
    `UPDATE observation_ingest_state
        SET fingerprint = ?, last_forwarded_at = 0
      WHERE observation_key LIKE 'v2:%'`,
  ).bind(revision).run().then((result) => {
    console.log(JSON.stringify({
      event: "observation_matching_invalidated",
      source,
      scopes: Number(result.meta.changes || 0),
    }));
  }).catch((error) => {
    console.warn(JSON.stringify({
      event: "observation_matching_invalidation_failed",
      source,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  });
}

async function ensureSchemaSafely(env: GateEnv, source: string): Promise<void> {
  try {
    const status = await ensureFreeTierSchema(env);
    if (status === "applied") {
      console.log(JSON.stringify({
        event: "free_tier_schema_applied",
        source,
      }));
    }
  } catch (error) {
    console.warn(JSON.stringify({
      event: "free_tier_schema_unavailable",
      source,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  }
}

function unchangedObservationResponse(
  envelope: FreeTierObservationEnvelope,
): Response {
  return Response.json({
    success: true,
    venueId: envelope.venueId,
    slotsAccepted: envelope.snapshot.slotCount,
    deduplicated: true,
    freeTierOptimized: true,
  }, {
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "application/json; charset=utf-8",
    },
  });
}

export default {
  async fetch(
    request: Request,
    env: GateEnv,
    context: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    let venueId: string | null = null;
    let observationPayload: unknown = null;
    const observationRequest = request.method === "POST"
      && url.pathname === "/api/internal/observations";
    if (observationRequest) {
      try {
        observationPayload = await request.clone().json<unknown>();
        venueId = observationVenueId(observationPayload);
      } catch {
        observationPayload = null;
        venueId = null;
      }
    }

    if (
      observationRequest
      && observationPayload
      && venueId
      && authorizedObservationRequest(request, env)
    ) {
      try {
        const decision = await applyFreeTierObservationPolicy(env.DB, observationPayload);
        if (decision.action === "skip" && decision.envelope) {
          console.log(JSON.stringify({
            event: "venue_observation_free_tier_deduplicated",
            venueId: decision.envelope.venueId,
            slotCount: decision.envelope.snapshot.slotCount,
          }));
          return unchangedObservationResponse(decision.envelope);
        }
      } catch (error) {
        console.warn(JSON.stringify({
          event: "free_tier_observation_policy_failed_open",
          venueId,
          reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
        }));
      }
    }

    const response = await worker.fetch(request, env as never, context);
    if (venueId) {
      return enrichObservationResponse(response, env, venueId);
    }

    if (response.ok && gateMutation(request.method, url.pathname)) {
      const source = `${request.method}:${url.pathname}`;
      context.waitUntil(Promise.all([
        refreshSafely(env, source),
        invalidateObservationMatchingSafely(env, source),
      ]).then(() => undefined));
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: GateEnv,
    context: ExecutionContext,
  ): Promise<void> {
    const cron = (controller as ScheduledController & { cron?: string }).cron;
    await ensureSchemaSafely(env, `scheduled:${cron || "unknown"}`);
    context.waitUntil(refreshSafely(env, `scheduled:${cron || "unknown"}`));
    await worker.scheduled(controller, env as never, context);
  },
} satisfies ExportedHandler<GateEnv>;
