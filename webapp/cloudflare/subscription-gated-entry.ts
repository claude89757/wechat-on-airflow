import worker from "./deployment-entry";
import {
  refreshWechatVenueGates,
  wechatGateForVenue,
} from "./wechat-subscription-gate";

type GateEnv = Env & {
  DB: D1Database;
};

function observationVenueId(payload: unknown): string | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  const candidate = payload as Record<string, unknown>;
  const venueId = String(candidate.venue_id ?? candidate.venueId ?? "").trim();
  return venueId || null;
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
    || pathname.startsWith("/api/admin/")
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

export default {
  async fetch(
    request: Request,
    env: GateEnv,
    context: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    let venueId: string | null = null;
    if (request.method === "POST" && url.pathname === "/api/internal/observations") {
      try {
        venueId = observationVenueId(await request.clone().json<unknown>());
      } catch {
        venueId = null;
      }
    }

    const response = await worker.fetch(request, env as never, context);
    if (venueId) {
      return enrichObservationResponse(response, env, venueId);
    }

    if (response.ok && gateMutation(request.method, url.pathname)) {
      context.waitUntil(refreshSafely(env, `${request.method}:${url.pathname}`));
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: GateEnv,
    context: ExecutionContext,
  ): Promise<void> {
    const cron = (controller as ScheduledController & { cron?: string }).cron;
    context.waitUntil(refreshSafely(env, `scheduled:${cron || "unknown"}`));
    await worker.scheduled(controller, env as never, context);
  },
} satisfies ExportedHandler<GateEnv>;
