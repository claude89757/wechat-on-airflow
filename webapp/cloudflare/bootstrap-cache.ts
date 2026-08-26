const BOOTSTRAP_CACHE_NAMESPACE = "https://bootstrap-cache.invalid/v1";

export const BOOTSTRAP_CACHE_TTL_SECONDS = 120;

type BootstrapCacheEnv = {
  VERIFICATION_PEPPER: string;
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
  token: string | null,
  pepper: string,
): Promise<Request> {
  const identity = token ? `receipt:${token}` : "anonymous";
  const digest = await sha256Hex(`zacks-bootstrap:${pepper}:${identity}`);
  return new Request(`${BOOTSTRAP_CACHE_NAMESPACE}/${digest}`, { method: "GET" });
}

function defaultCache(): Cache {
  return (caches as unknown as { default: Cache }).default;
}

function clientResponse(response: Response, cacheStatus: "hit" | "miss"): Response {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", "no-store");
  headers.set("X-Zacks-Bootstrap-Cache", cacheStatus);
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

export async function matchBootstrapCache(
  request: Request,
  env: BootstrapCacheEnv,
): Promise<Response | null> {
  const cached = await defaultCache().match(
    await bootstrapCacheRequest(requestToken(request), env.VERIFICATION_PEPPER),
  );
  return cached ? clientResponse(cached, "hit") : null;
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
  headers.set("Cache-Control", `public, max-age=${BOOTSTRAP_CACHE_TTL_SECONDS}`);
  headers.set("X-Zacks-Bootstrap-Cache", "miss");
  await defaultCache().put(
    await bootstrapCacheRequest(requestToken(request), env.VERIFICATION_PEPPER),
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
  const keys = [await bootstrapCacheRequest(token, env.VERIFICATION_PEPPER)];
  if (includeAnonymous && token) {
    keys.push(await bootstrapCacheRequest(null, env.VERIFICATION_PEPPER));
  }
  await Promise.all(keys.map((key) => defaultCache().delete(key)));
}

export function bootstrapCacheMiss(response: Response): Response {
  return clientResponse(response, "miss");
}
