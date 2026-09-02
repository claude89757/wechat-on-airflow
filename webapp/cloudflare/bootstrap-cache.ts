const BOOTSTRAP_CACHE_PATH = "/__zacks_edge_cache/bootstrap";
const BOOTSTRAP_CACHE_STORED_AT_HEADER = "X-Zacks-Bootstrap-Stored-At";

// Five minutes is the freshness window. A successful payload is retained for
// two days so a transient D1 outage can show the last known data instead of a
// blank dashboard. The longer retention is internal to Cache API; clients
// always receive Cache-Control: no-store.
export const BOOTSTRAP_CACHE_TTL_SECONDS = 300;
export const BOOTSTRAP_CACHE_RETENTION_SECONDS = 2 * 24 * 60 * 60;

type BootstrapCacheEnv = {
  VERIFICATION_PEPPER: string;
};

type BootstrapCacheMatchOptions = {
  allowStale?: boolean;
  now?: number;
};

function requestToken(request: Request): string | null {
  const authorization = request.headers.get("authorization") || "";
  return authorization.startsWith("Bearer ")
    ? authorization.slice(7).trim() || null
    : null;
}

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

export async function bootstrapCacheRequest(
  requestUrl: string,
  token: string | null,
  pepper: string,
): Promise<Request> {
  const identity = token ? `receipt:${token}` : "anonymous";
  const digest = await sha256Hex(`zacks-bootstrap:${pepper}:${identity}`);
  const url = new URL(requestUrl);
  url.pathname = `${BOOTSTRAP_CACHE_PATH}/${digest}`;
  url.search = "";
  url.hash = "";
  return new Request(url.toString(), { method: "GET" });
}

function defaultCache(): Cache {
  return (caches as unknown as { default: Cache }).default;
}

function clientResponse(
  response: Response,
  cacheStatus: "hit" | "miss" | "stale",
): Response {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", "no-store");
  headers.set("X-Zacks-Bootstrap-Cache", cacheStatus);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

async function cacheKey(
  request: Request,
  env: BootstrapCacheEnv,
  token = requestToken(request),
): Promise<Request> {
  return bootstrapCacheRequest(request.url, token, env.VERIFICATION_PEPPER);
}

export function bootstrapCacheAgeSeconds(
  response: Response,
  now = Date.now(),
): number | null {
  const storedAt = Date.parse(response.headers.get(BOOTSTRAP_CACHE_STORED_AT_HEADER) || "");
  if (!Number.isFinite(storedAt)) return null;
  return Math.max(0, Math.floor((now - storedAt) / 1000));
}

export async function matchBootstrapCache(
  request: Request,
  env: BootstrapCacheEnv,
  options: BootstrapCacheMatchOptions = {},
): Promise<Response | null> {
  const cached = await defaultCache().match(await cacheKey(request, env));
  if (!cached) return null;

  const ageSeconds = bootstrapCacheAgeSeconds(cached, options.now);
  const stale = ageSeconds === null || ageSeconds > BOOTSTRAP_CACHE_TTL_SECONDS;
  if (stale && !options.allowStale) return null;
  return clientResponse(cached, stale ? "stale" : "hit");
}

export async function storeBootstrapCache(
  request: Request,
  env: BootstrapCacheEnv,
  response: Response,
): Promise<void> {
  if (!response.ok) return;
  const headers = new Headers(response.headers);
  headers.delete("Set-Cookie");
  headers.delete("Vary");
  headers.set("Cache-Control", `public, max-age=${BOOTSTRAP_CACHE_RETENTION_SECONDS}`);
  headers.set(BOOTSTRAP_CACHE_STORED_AT_HEADER, new Date().toISOString());
  headers.set("X-Zacks-Bootstrap-Cache", "miss");
  await defaultCache().put(
    await cacheKey(request, env),
    new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    }),
  );
}

export async function invalidateBootstrapCache(
  request: Request,
  env: BootstrapCacheEnv,
  includeAnonymous = false,
): Promise<void> {
  const token = requestToken(request);
  const keys = [await cacheKey(request, env, token)];
  if (includeAnonymous && token) {
    keys.push(await cacheKey(request, env, null));
  }
  await Promise.all(keys.map((key) => defaultCache().delete(key)));
}

export function bootstrapCacheMiss(response: Response): Response {
  return clientResponse(response, "miss");
}
