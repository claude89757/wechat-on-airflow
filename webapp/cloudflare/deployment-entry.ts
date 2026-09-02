import worker from "./index";
import {
  bootstrapCacheMiss,
  invalidateBootstrapCache,
  matchBootstrapCache,
  storeBootstrapCache,
} from "./bootstrap-cache";
import {
  providerCheckError,
  reconcileDeliveryStatuses,
  type DeliveryReconcileSummary,
} from "./delivery-reconcile";
import {
  decideObservationDedupe,
  recordForwardedObservation,
  type ObservationSnapshot,
} from "./observation-dedupe";
import { PRIORITY_WEATHER_BYPASS_ENABLED } from "./weather-delivery-policy";

type DeploymentEnv = Env & {
  DEPLOYMENT_COMMIT?: string;
  VERIFICATION_PEPPER: string;
  AIRFLOW_PUSH_TOKEN: string;
  INVITE_CODE_PEPPER?: string;
  INVITE_ADMIN_TOKEN?: string;
  TENCENT_SECRET_ID: string;
  TENCENT_SECRET_KEY: string;
  TENCENT_REGION: string;
  EMAIL_FROM_ADDRESS: string;
  EMAIL_REPLY_TO: string;
  EMAIL_TEMPLATE_ID: string;
};

export const DELIVERY_RECONCILE_CRON = "*/5 * * * *";
export const MAINTENANCE_CRON = "17 * * * *";
const DELIVERY_RECONCILE_BATCH = 5;

export function deploymentHealth(deploymentCommit?: string) {
  return {
    ok: true,
    service: "zacks-tennis-alerts",
    capabilities: {
      priorityWeatherBypass: PRIORITY_WEATHER_BYPASS_ENABLED,
    },
    deploymentCommit:
      typeof deploymentCommit === "string" && /^[0-9a-f]{40}$/i.test(deploymentCommit)
        ? deploymentCommit
        : "unknown",
  };
}

export function shanghaiDayStartIso(now = new Date()): string {
  const shifted = new Date(now.getTime() + 8 * 3_600_000);
  return new Date(
    Date.UTC(
      shifted.getUTCFullYear(),
      shifted.getUTCMonth(),
      shifted.getUTCDate(),
    ) - 8 * 3_600_000,
  ).toISOString();
}

export function shanghaiDeliveryDay(now = new Date()): string {
  return new Date(now.getTime() + 8 * 3_600_000).toISOString().slice(0, 10);
}

export function applyGlobalSubmittedReminderMetric(
  payload: unknown,
  submittedToday: number,
): unknown {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return payload;
  const root = payload as Record<string, unknown>;
  if (!root.metrics || typeof root.metrics !== "object" || Array.isArray(root.metrics)) {
    return payload;
  }
  const count = Number.isFinite(submittedToday)
    ? Math.max(0, Math.trunc(submittedToday))
    : 0;
  return {
    ...root,
    metrics: {
      ...(root.metrics as Record<string, unknown>),
      remindersToday: count,
    },
  };
}

export function scheduledWorkForCron(
  cron: string | undefined,
): "delivery_reconcile" | "maintenance" {
  return cron === MAINTENANCE_CRON ? "maintenance" : "delivery_reconcile";
}

export function invalidatesBootstrap(method: string, pathname: string): boolean {
  return (
    (method === "POST" && pathname === "/api/subscriptions")
    || (method === "POST" && pathname === "/api/priority/redeem")
    || (method === "DELETE" && /^\/api\/subscriptions\/[0-9a-f-]{36}$/i.test(pathname))
  );
}

export function bypassesBootstrapCache(request: Request): boolean {
  const url = new URL(request.url);
  return request.method === "GET"
    && url.pathname === "/api/bootstrap"
    && url.searchParams.get("refresh") === "1";
}

export function nextD1QuotaResetIso(now = new Date()): string {
  return new Date(Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + 1,
  )).toISOString();
}

export function bootstrapFailureCanUseStale(
  status: number,
  body: string,
): boolean {
  if ([401, 403, 404].includes(status)) return false;
  if (status === 408 || status === 429 || status >= 500) return true;
  if (status !== 400) return false;
  return /D1(?:_ERROR)?|daily row read limit|code[:\s]*7500|database (?:is )?(?:unavailable|temporarily unavailable)/i.test(body);
}

async function staleBootstrapResponse(
  response: Response,
  now = new Date(),
): Promise<Response> {
  try {
    const payload = await response.clone().json<unknown>();
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) return response;
    const headers = new Headers(response.headers);
    headers.delete("Content-Length");
    headers.delete("Content-Encoding");
    headers.set("Cache-Control", "no-store");
    headers.set("Content-Type", "application/json; charset=utf-8");
    headers.set("X-Zacks-Bootstrap-Cache", "stale");
    return new Response(JSON.stringify({
      ...(payload as Record<string, unknown>),
      dataStatus: {
        stale: true,
        source: "edge-cache",
        reason: "data_store_unavailable",
        retryAt: nextD1QuotaResetIso(now),
      },
    }), {
      status: 200,
      headers,
    });
  } catch {
    return response;
  }
}

function withInviteSecrets(env: DeploymentEnv) {
  return {
    ...env,
    INVITE_CODE_PEPPER: env.INVITE_CODE_PEPPER || env.VERIFICATION_PEPPER,
    INVITE_ADMIN_TOKEN: env.INVITE_ADMIN_TOKEN || env.AIRFLOW_PUSH_TOKEN,
  };
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

function authorizedInternalRequest(request: Request, env: DeploymentEnv): boolean {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) return false;
  const token = authorization.slice(7).trim();
  return Boolean(token) && constantTimeEqual(token, env.AIRFLOW_PUSH_TOKEN);
}

function unavailableCount(summary: DeliveryReconcileSummary): number {
  return summary.notifications.unavailable + summary.systemEmails.unavailable;
}

async function reconcileSafely(
  env: DeploymentEnv,
  limit: number,
  source: string,
): Promise<DeliveryReconcileSummary | null> {
  try {
    const summary = await reconcileDeliveryStatuses(withInviteSecrets(env) as never, limit);
    console.log(JSON.stringify({
      event: "delivery_reconcile_completed",
      source,
      summary,
    }));
    return summary;
  } catch (error) {
    const detail = providerCheckError(error);
    console.warn(JSON.stringify({
      event: "delivery_reconcile_failed",
      source,
      errorCode: detail.code,
    }));
    return null;
  }
}

async function rewriteBootstrapReminderMetric(
  response: Response,
  env: DeploymentEnv,
): Promise<Response> {
  try {
    const [payload, row] = await Promise.all([
      response.clone().json<unknown>(),
      env.DB.prepare(
        `SELECT COUNT(*) AS count
           FROM email_delivery_claims
          WHERE delivery_day = ?
            AND status = 'sent'`,
      ).bind(shanghaiDeliveryDay()).first<{ count?: number }>(),
    ]);
    const corrected = applyGlobalSubmittedReminderMetric(
      payload,
      Number(row?.count || 0),
    );
    const headers = new Headers(response.headers);
    headers.delete("Content-Length");
    headers.delete("Content-Encoding");
    headers.set("Cache-Control", "no-store");
    headers.set("Content-Type", "application/json; charset=utf-8");
    return new Response(JSON.stringify(corrected), {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  } catch (error) {
    console.warn(JSON.stringify({
      event: "bootstrap_reminder_metric_correction_failed",
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
    return response;
  }
}

async function cachedBootstrap(
  request: Request,
  env: DeploymentEnv,
  allowStale = false,
): Promise<Response | null> {
  try {
    return await matchBootstrapCache(request, env, { allowStale });
  } catch (error) {
    console.warn(JSON.stringify({
      event: "bootstrap_cache_read_failed",
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
    return null;
  }
}

function storeBootstrapSafely(
  request: Request,
  env: DeploymentEnv,
  response: Response,
): Promise<void> {
  return storeBootstrapCache(request, env, response).catch((error) => {
    console.warn(JSON.stringify({
      event: "bootstrap_cache_write_failed",
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  });
}

async function invalidateBootstrapSafely(
  request: Request,
  env: DeploymentEnv,
): Promise<void> {
  try {
    await invalidateBootstrapCache(request, env, true);
  } catch (error) {
    console.warn(JSON.stringify({
      event: "bootstrap_cache_invalidation_failed",
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  }
}

async function observationDecision(
  request: Request,
  env: DeploymentEnv,
): Promise<{ skip: Response | null; snapshot: ObservationSnapshot | null }> {
  try {
    const decision = await decideObservationDedupe(
      env.DB,
      await request.clone().json<unknown>(),
    );
    if (decision.action === "skip" && decision.snapshot) {
      console.log(JSON.stringify({
        event: "venue_observation_deduplicated",
        venueId: decision.snapshot.venueId,
        slotCount: decision.snapshot.slotCount,
      }));
      return {
        skip: Response.json({
          success: true,
          venueId: decision.snapshot.venueId,
          slotsAccepted: decision.snapshot.slotCount,
          deduplicated: true,
        }, {
          headers: {
            "Cache-Control": "no-store",
            "Content-Type": "application/json; charset=utf-8",
          },
        }),
        snapshot: decision.snapshot,
      };
    }
    return { skip: null, snapshot: decision.snapshot };
  } catch (error) {
    console.warn(JSON.stringify({
      event: "venue_observation_dedupe_failed_open",
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
    return { skip: null, snapshot: null };
  }
}

async function recordObservationSafely(
  env: DeploymentEnv,
  snapshot: ObservationSnapshot,
): Promise<void> {
  try {
    await recordForwardedObservation(env.DB, snapshot);
  } catch (error) {
    console.warn(JSON.stringify({
      event: "venue_observation_dedupe_record_failed",
      venueId: snapshot.venueId,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
  }
}

export default {
  async fetch(
    request: Request,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/healthz") {
      return Response.json(deploymentHealth(env.DEPLOYMENT_COMMIT), {
        headers: {
          "Cache-Control": "no-store",
          "Content-Type": "application/json; charset=utf-8",
        },
      });
    }

    if (request.method === "POST" && url.pathname === "/api/internal/reconcile-deliveries") {
      if (!authorizedInternalRequest(request, env)) {
        return Response.json({ error: "未授权" }, { status: 401 });
      }
      try {
        const summary = await reconcileDeliveryStatuses(
          withInviteSecrets(env) as never,
          DELIVERY_RECONCILE_BATCH,
        );
        const unavailable = unavailableCount(summary);
        return Response.json({
          success: unavailable === 0,
          unavailable,
          ...summary,
        }, {
          status: unavailable === 0 ? 200 : 502,
          headers: { "Cache-Control": "no-store" },
        });
      } catch (error) {
        const detail = providerCheckError(error);
        console.error(JSON.stringify({
          event: "protected_delivery_reconcile_failed",
          errorCode: detail.code,
        }));
        return Response.json({
          success: false,
          errorCode: detail.code,
        }, {
          status: 500,
          headers: { "Cache-Control": "no-store" },
        });
      }
    }

    const bootstrapRequest = request.method === "GET"
      && url.pathname === "/api/bootstrap";
    const bypassBootstrapCache = bootstrapRequest && bypassesBootstrapCache(request);
    if (bootstrapRequest && !bypassBootstrapCache) {
      const cached = await cachedBootstrap(request, env);
      if (cached) return cached;
    }

    let observationSnapshot: ObservationSnapshot | null = null;
    if (
      request.method === "POST"
      && url.pathname === "/api/internal/observations"
      && authorizedInternalRequest(request, env)
    ) {
      const decision = await observationDecision(request, env);
      if (decision.skip) return decision.skip;
      observationSnapshot = decision.snapshot;
    }

    const response = await worker.fetch(request, withInviteSecrets(env) as never, context);
    if (response.ok && bootstrapRequest) {
      const corrected = await rewriteBootstrapReminderMetric(response, env);
      context.waitUntil(storeBootstrapSafely(request, env, corrected.clone()));
      return bootstrapCacheMiss(corrected);
    }

    if (bootstrapRequest && !bypassBootstrapCache && !response.ok) {
      const body = await response.clone().text().catch(() => "");
      if (bootstrapFailureCanUseStale(response.status, body)) {
        const stale = await cachedBootstrap(request, env, true);
        if (stale) {
console.warn(JSON.stringify({
  event: "bootstrap_stale_fallback_served",
  status: response.status,
}));
return staleBootstrapResponse(stale);
        }
      }
    }

    if (response.ok && observationSnapshot) {
      await recordObservationSafely(env, observationSnapshot);
    }

    if (response.ok && invalidatesBootstrap(request.method, url.pathname)) {
      await invalidateBootstrapSafely(request, env);
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<void> {
    const cron = (controller as ScheduledController & { cron?: string }).cron;
    if (scheduledWorkForCron(cron) === "maintenance") {
      await worker.scheduled(controller, withInviteSecrets(env) as never, context);
      return;
    }
    await reconcileSafely(env, DELIVERY_RECONCILE_BATCH, `scheduled:${cron || "unknown"}`);
  },
} satisfies ExportedHandler<DeploymentEnv>;
