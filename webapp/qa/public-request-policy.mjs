// Acceptance never sends writes, including Cloudflare's injected analytics.
// Count only the exact same-origin RUM beacon separately from application writes.
export function acceptanceRequestPolicy(method, requestUrl, pageOrigin) {
  if (["GET", "HEAD", "OPTIONS"].includes(method)) return "read";
  const url = new URL(requestUrl);
  if (method === "POST" && url.origin === pageOrigin && url.pathname === "/cdn-cgi/rum") {
    return "blocked-cloudflare-telemetry";
  }
  return "blocked-write";
}
