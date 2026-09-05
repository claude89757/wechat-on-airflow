/** Production edge: no database bindings, migration handlers, or legacy dispatch. */
export type EdgeEnv = {
  ASSETS: Fetcher;
  AIRFLOW_PUSH_TOKEN: string;
  DEPLOYMENT_COMMIT?: string;
  HOST_CORE_ORIGIN_URL?: string;
};
const DEFAULT_ORIGIN = "https://airflow.claude89757.cc/zacks-api";

export function hostCoreOrigin(value: unknown): URL {
  const url = new URL(String(value || DEFAULT_ORIGIN).trim() || DEFAULT_ORIGIN);
  if (url.protocol !== "https:") throw new Error("HOST_CORE_ORIGIN_URL must use HTTPS");
  return url;
}

export function edgeDeploymentHealth(env: EdgeEnv): Record<string, unknown> {
  return {
    ok: true, service: "zacks-tennis-edge", runtime: "cloudflare-stateless-edge",
    deploymentCommit: /^[0-9a-f]{40}$/.test(env.DEPLOYMENT_COMMIT || "")
      ? env.DEPLOYMENT_COMMIT : "unknown",
    cutover: true, quiesced: false, migrationEndpoint: false, durableBusinessState: "none",
    legacyRuntime: false,
  };
}

function securityHeaders(headers: Headers): Headers {
  const next = new Headers(headers);
  next.set("X-Content-Type-Options", "nosniff");
  next.set("Referrer-Policy", "strict-origin-when-cross-origin");
  next.set("Permissions-Policy", "camera=(), microphone=(), geolocation=()");
  return next;
}

export function originRequest(request: Request, env: EdgeEnv): Request {
  const source = new URL(request.url);
  const origin = hostCoreOrigin(env.HOST_CORE_ORIGIN_URL);
  origin.pathname = `${origin.pathname.replace(/\/$/, "")}${source.pathname}`;
  origin.search = source.search;
  const headers = new Headers(request.headers);
  for (const key of ["host", "cf-connecting-ip", "cf-ray", "cf-visitor", "x-zacks-edge-token", "x-zacks-client-ip", "x-zacks-edge-commit"]) {
    headers.delete(key);
  }
  headers.set("X-Zacks-Edge-Token", env.AIRFLOW_PUSH_TOKEN);
  headers.set("X-Zacks-Client-IP", request.headers.get("cf-connecting-ip") || "unknown");
  headers.set("X-Zacks-Edge-Commit", env.DEPLOYMENT_COMMIT || "unknown");
  return new Request(origin.toString(), {
    method: request.method, headers,
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
    redirect: "manual", signal: AbortSignal.timeout(15000),
  });
}

export default {
  async fetch(request: Request, env: EdgeEnv): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (["GET", "HEAD"].includes(request.method) && path === "/api/edge-healthz") {
      return Response.json(edgeDeploymentHealth(env), { headers: { "Cache-Control": "no-store" } });
    }
    // Internal collector/administration paths are never exposed through the public edge.
    if (path.startsWith("/api/internal/")) return Response.json({error: "未找到"}, {status: 404});
    if (!path.startsWith("/api/")) {
      const asset = await env.ASSETS.fetch(request);
      return new Response(asset.body, {status: asset.status, headers: securityHeaders(asset.headers)});
    }
    try {
      if (!env.AIRFLOW_PUSH_TOKEN) throw new Error("origin authentication unavailable");
      const response = await fetch(originRequest(request, env));
      const headers = securityHeaders(response.headers);
      headers.delete("Content-Length"); headers.delete("Content-Encoding");
      headers.set("Cache-Control", "no-store"); headers.set("X-Zacks-Edge", "airflow-host-proxy");
      return new Response(response.body, {status: response.status, statusText: response.statusText, headers});
    } catch {
      return Response.json({error: "服务暂时不可用，请稍后重试", source: "airflow-host",
        dataStatus: {stale: true, source: "browser-cache", reason: "data_store_unavailable", retryAt: null}},
      {status: 503, headers: {"Cache-Control": "no-store", "Retry-After": "30"}});
    }
  },
  async scheduled(): Promise<void> {
    // Defensive no-op for any delayed trigger from a superseded deployment.
  },
} satisfies ExportedHandler<EdgeEnv>;
