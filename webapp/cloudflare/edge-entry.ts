import legacyWorker from "./subscription-gated-entry";
import { hostMigrationExport } from "./host-migration-export";

type EdgeEnv = Env & {
  ASSETS: Fetcher;
  AIRFLOW_PUSH_TOKEN: string;
  DEPLOYMENT_COMMIT?: string;
  HOST_CORE_CUTOVER?: string;
  HOST_CORE_QUIESCE?: string;
  HOST_CORE_MIGRATION_ENABLED?: string;
  HOST_CORE_ORIGIN_URL?: string;
};

const DEFAULT_ORIGIN = "https://airflow.claude89757.cc/zacks-api";
const MIGRATION_PATHS = new Set([
  "/api/internal/host-migration-export",
  "/api/internal/host-secret-envelope",
]);

function enabled(value: unknown): boolean {
  return ["1", "true", "yes", "on"].includes(String(value || "").trim().toLowerCase());
}

export function hostCoreCutoverEnabled(value: unknown): boolean {
  return enabled(value);
}

export function hostCoreQuiesceEnabled(value: unknown): boolean {
  return enabled(value);
}

export function hostCoreMigrationEnabled(value: unknown): boolean {
  return enabled(value);
}

export function hostCoreOrigin(value: unknown): URL {
  const candidate = String(value || DEFAULT_ORIGIN).trim() || DEFAULT_ORIGIN;
  const url = new URL(candidate);
  if (url.protocol !== "https:") throw new Error("HOST_CORE_ORIGIN_URL must use HTTPS");
  return url;
}

function securityHeaders(headers: Headers): Headers {
  const next = new Headers(headers);
  next.set("X-Content-Type-Options", "nosniff");
  next.set("Referrer-Policy", "strict-origin-when-cross-origin");
  next.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return next;
}

function originRequest(request: Request, env: EdgeEnv): Request {
  const source = new URL(request.url);
  const origin = hostCoreOrigin(env.HOST_CORE_ORIGIN_URL);
  const basePath = origin.pathname.replace(/\/$/, "");
  origin.pathname = `${basePath}${source.pathname}`;
  origin.search = source.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("cf-connecting-ip");
  headers.delete("cf-ray");
  headers.delete("cf-visitor");
  headers.delete("x-zacks-edge-token");
  headers.delete("x-zacks-client-ip");
  headers.set("X-Zacks-Edge-Token", env.AIRFLOW_PUSH_TOKEN);
  headers.set("X-Zacks-Client-IP", request.headers.get("cf-connecting-ip") || "unknown");
  headers.set("X-Zacks-Edge-Commit", env.DEPLOYMENT_COMMIT || "unknown");
  return new Request(origin.toString(), {
    method: request.method,
    headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    redirect: "manual",
  });
}

async function proxyApi(request: Request, env: EdgeEnv): Promise<Response> {
  try {
    const response = await fetch(originRequest(request, env));
    const headers = securityHeaders(response.headers);
    headers.delete("Content-Length");
    headers.delete("Content-Encoding");
    headers.set("Cache-Control", "no-store");
    headers.set("X-Zacks-Edge", "airflow-host-proxy");
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  } catch (error) {
    console.warn(JSON.stringify({
      event: "host_core_origin_unavailable",
      path: new URL(request.url).pathname,
      reason: error instanceof Error ? error.message.slice(0, 160) : "unknown",
    }));
    return Response.json({
      error: "服务暂时不可用，请稍后再试",
      dataStatus: {
        stale: true,
        source: "browser-cache",
        reason: "data_store_unavailable",
        retryAt: null,
      },
    }, {
      status: 503,
      headers: {
        "Cache-Control": "no-store",
        "Retry-After": "30",
        "X-Zacks-Edge": "origin-unavailable",
      },
    });
  }
}

function quiesceBlocks(request: Request): boolean {
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/api/")) return false;
  if (MIGRATION_PATHS.has(url.pathname)) return false;
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return false;
  return true;
}

function quiescedResponse(): Response {
  return Response.json({
    error: "系统正在进行无中断迁移，请稍后重试",
    maintenance: true,
  }, {
    status: 503,
    headers: {
      "Cache-Control": "no-store",
      "Retry-After": "30",
    },
  });
}

export default {
  async fetch(
    request: Request,
    env: EdgeEnv,
    context: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    if (MIGRATION_PATHS.has(url.pathname)) {
      if (!hostCoreMigrationEnabled(env.HOST_CORE_MIGRATION_ENABLED)) {
        return Response.json({ error: "迁移端点未启用" }, { status: 404 });
      }
      return hostMigrationExport(request, env);
    }

    if (hostCoreQuiesceEnabled(env.HOST_CORE_QUIESCE) && quiesceBlocks(request)) {
      return quiescedResponse();
    }

    if (!hostCoreCutoverEnabled(env.HOST_CORE_CUTOVER)) {
      return legacyWorker.fetch(request, env as never, context);
    }

    if (url.pathname.startsWith("/api/")) {
      return proxyApi(request, env);
    }

    const asset = await env.ASSETS.fetch(request);
    return new Response(asset.body, {
      status: asset.status,
      statusText: asset.statusText,
      headers: securityHeaders(asset.headers),
    });
  },

  async scheduled(
    controller: ScheduledController,
    env: EdgeEnv,
    context: ExecutionContext,
  ): Promise<void> {
    const cron = (controller as ScheduledController & { cron?: string }).cron || "unknown";
    if (
      !hostCoreCutoverEnabled(env.HOST_CORE_CUTOVER)
      && !hostCoreQuiesceEnabled(env.HOST_CORE_QUIESCE)
    ) {
      await legacyWorker.scheduled(controller, env as never, context);
      return;
    }
    console.log(JSON.stringify({
      event: "cloudflare_edge_cron_ignored_after_host_cutover",
      cron,
      cutover: hostCoreCutoverEnabled(env.HOST_CORE_CUTOVER),
      quiesced: hostCoreQuiesceEnabled(env.HOST_CORE_QUIESCE),
    }));
  },
} satisfies ExportedHandler<EdgeEnv>;
