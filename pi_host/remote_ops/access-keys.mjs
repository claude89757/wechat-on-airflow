import { get } from "node:https";
import { createRemoteJWKSet, customFetch } from "jose";

export const CERTS_URL = "https://zacks-vision-ops.cloudflareaccess.com/cdn-cgi/access/certs";
export class KeysUnavailable extends Error {
  constructor() { super("authentication_dependency_unavailable"); }
}

// Scope IPv4 to this public-key dependency, without changing global DNS or TLS.
export function downloadKeys(url, { signal }, request = get) {
  if (url !== CERTS_URL) return Promise.reject(new KeysUnavailable());
  return new Promise((resolve, reject) => {
    const req = request(url, { family: 4, agent: false, signal,
      headers: { accept: "application/json" } }, res => {
      const chunks = []; let size = 0;
      res.on("error", reject);
      res.on("data", chunk => {
        size += chunk.length;
        if (size > 65536) { res.destroy(); reject(new KeysUnavailable()); }
        else chunks.push(chunk);
      });
      res.on("end", () => {
        try {
          if (res.statusCode !== 200) throw new KeysUnavailable();
          const value = JSON.parse(Buffer.concat(chunks).toString("utf8"));
          if (!Array.isArray(value.keys) || !value.keys.length) throw new KeysUnavailable();
          resolve(new Response(JSON.stringify(value), { status: 200 }));
        } catch { reject(new KeysUnavailable()); }
      });
    });
    req.on("error", reject);
  });
}

export function keyFetcher(download = downloadKeys, timeoutMs = 6000) {
  return async (url, options) => {
    // Retry only the idempotent public-key GET, never an MCP command or token validation.
    for (let attempt = 0; attempt < 2; attempt++) {
      if (options.signal.aborted) break;
      try {
        return await download(url, { signal: AbortSignal.any([
          options.signal, AbortSignal.timeout(timeoutMs),
        ]) });
      } catch { /* A second bounded connection can recover a transient network failure. */ }
    }
    throw new KeysUnavailable();
  };
}

export function createAccessKeys(options = {}) {
  return createRemoteJWKSet(new URL(CERTS_URL), {
    timeoutDuration: 15000, cacheMaxAge: 600000, cooldownDuration: 30000,
    [customFetch]: keyFetcher(), ...options,
  });
}
