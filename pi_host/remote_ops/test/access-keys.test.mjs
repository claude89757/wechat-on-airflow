import { test } from "node:test";
import assert from "node:assert/strict";
import { EventEmitter, once } from "node:events";
import { PassThrough } from "node:stream";
import { generateKeyPair, exportJWK, SignJWT, jwtVerify, customFetch } from "jose";
import { CERTS_URL, KeysUnavailable, downloadKeys, keyFetcher, createAccessKeys } from "../access-keys.mjs";
import { createOpsServer } from "../server.mjs";

test("public key transport uses IPv4, bounded bodies and normal TLS, with no auth headers", async () => {
  const request = (status, body) => (url, options, receive) => {
    assert.equal(url, CERTS_URL);
    assert.equal(options.family, 4);
    assert.equal(options.agent, false);
    assert.equal(options.rejectUnauthorized, undefined);
    assert.deepEqual(options.headers, { accept: "application/json" });
    const req = new EventEmitter();
    queueMicrotask(() => {
      const response = new PassThrough(); response.statusCode = status;
      receive(response); response.end(body);
    });
    return req;
  };
  const options = { signal: AbortSignal.timeout(1000) };
  assert.equal((await downloadKeys(CERTS_URL, options, request(200, '{"keys":[{}]}'))).status, 200);
  for (const [status, body] of [[302, ""], [500, ""], [200, "invalid"], [200, '{"keys":[]}'], [200, "x".repeat(65537)]]) {
    await assert.rejects(downloadKeys(CERTS_URL, options, request(status, body)), KeysUnavailable);
  }
  await assert.rejects(downloadKeys("https://untrusted.invalid", options), KeysUnavailable);
});

test("key download retries once, respects time limits and fails closed", async () => {
  let attempts = 0;
  const fetch = keyFetcher(async () => {
    if (++attempts === 1) throw Error("private-network-detail");
    return new Response('{"keys":[{}]}');
  });
  const options = { signal: AbortSignal.timeout(1000) };
  assert.equal((await fetch(CERTS_URL, options)).status, 200);
  assert.equal(attempts, 2);
  attempts = 0;
  const unavailable = keyFetcher(async (_url, { signal }) => {
    attempts++;
    await new Promise((_, reject) => signal.addEventListener("abort", () => reject(signal.reason), { once: true }));
  }, 5);
  // Keep the test alive while AbortSignal's unref'ed timeout fires.
  const keepAlive = setInterval(() => {}, 1000);
  try {
    await assert.rejects(unavailable(CERTS_URL, options), KeysUnavailable);
    assert.equal(attempts, 2);
    const controller = new AbortController(); controller.abort();
    await assert.rejects(unavailable(CERTS_URL, { signal: controller.signal }), KeysUnavailable);
    assert.equal(attempts, 2);
  } finally { clearInterval(keepAlive); }
});

test("resolver caches valid keys, refreshes rotated keys, and never accepts stale keys on outage", async () => {
  const pair = await generateKeyPair("RS256");
  const jwk = { ...await exportJWK(pair.publicKey), kid: "first" };
  let calls = 0, broken = false, kid = "first";
  const options = { cooldownDuration: 0, [customFetch]: async () => {
    calls++; if (broken) throw new KeysUnavailable();
    return new Response(JSON.stringify({ keys: [{ ...jwk, kid }] }));
  } };
  const keys = createAccessKeys(options);
  const token = key => new SignJWT({}).setProtectedHeader({ alg: "RS256", kid: key })
    .setIssuer("test").setAudience("test").setIssuedAt().setExpirationTime("1m").sign(pair.privateKey);
  const verify = value => jwtVerify(value, keys, { issuer: "test", audience: "test", algorithms: ["RS256"] });
  const first = await token("first");
  await verify(first); await verify(first); assert.equal(calls, 1);
  kid = "second"; await verify(await token(kid)); assert.equal(calls, 2);
  const cold = createAccessKeys({ ...options, cacheMaxAge: 0 });
  await cold.reload(); broken = true;
  await assert.rejects(jwtVerify(await token(kid), cold), KeysUnavailable);
});

test("public key outages return 503 and sanitized correlation evidence, not permission denied", async () => {
  const events = [];
  const server = createOpsServer({ origin: "https://pi-mcp.zacks.vision", target: "pi", commit: "a".repeat(40),
    issuer: "https://zacks-vision-ops.cloudflareaccess.com", audience: "test" },
  { keys: async () => { throw new KeysUnavailable(); }, audit: e => events.push(e) });
  const pair = await generateKeyPair("RS256");
  const token = await new SignJWT({ secret: "do-not-log" }).setProtectedHeader({ alg: "RS256" }).sign(pair.privateKey);
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  try {
    const response = await fetch(`http://127.0.0.1:${server.address().port}/mcp`, {
      method: "POST", headers: { "cf-access-jwt-assertion": token }, body: "{}",
    });
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("retry-after"), "5");
    const body = await response.json();
    assert.equal(body.error, "authentication_dependency_unavailable");
    assert.equal(events[0].requestId, body.requestId);
    assert.equal(JSON.stringify(events).includes(token), false);
    assert.equal(JSON.stringify(events).includes("do-not-log"), false);
  } finally { server.closeAllConnections(); server.close(); await once(server, "close"); }
});
