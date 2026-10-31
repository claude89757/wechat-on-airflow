import { test } from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { spawn } from "node:child_process";
import { mkdtempSync, writeFileSync, symlinkSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "node:net";
import { generateKeyPair, exportJWK, SignJWT, createLocalJWKSet } from "jose";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { createOpsServer } from "../server.mjs";

test("systemd-style symlink entrypoint actually starts the HTTP server", { timeout: 15000 }, async () => {
  const reserve = createServer().listen(0, "127.0.0.1");
  await once(reserve, "listening");
  const port = reserve.address().port;
  reserve.close(); await once(reserve, "close");
  const directory = mkdtempSync(join(tmpdir(), "ops-entrypoint-"));
  const entry = join(directory, "current.mjs"), config = join(directory, "runtime.json");
  symlinkSync(fileURLToPath(new URL("../server.mjs", import.meta.url)), entry);
  writeFileSync(config, JSON.stringify({ origin: "https://pi-mcp.zacks.vision", target: "pi",
    commit: "a".repeat(40), issuer: "https://zacks-vision-ops.cloudflareaccess.com",
    audience: "isolated-audience", port }));
  const child = spawn(process.execPath, [entry], { env: { ...process.env, OPS_CONFIG: config }, stdio: "ignore" });
  try {
    let report;
    for (let attempt = 0; attempt < 100; attempt++) {
      assert.equal(child.exitCode, null, "server exited before opening its listener");
      try { report = await (await fetch(`http://127.0.0.1:${port}/healthz`)).json(); break; } catch {}
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    assert.equal(report?.commit, "a".repeat(40));
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      const closed = once(child, "close"); child.kill(); await closed;
    }
    rmSync(directory, { recursive: true, force: true });
  }
});

test("real HTTP MCP verifies JWT, isolates users and requires browser-only confirmation", async () => {
  const { privateKey, publicKey } = await generateKeyPair("RS256");
  const jwk = { ...await exportJWK(publicKey), kid: "test" };
  const config = { origin: "https://pi-mcp.zacks.vision", target: "pi", commit: "a".repeat(40),
    issuer: "https://zacks-vision-ops.cloudflareaccess.com", audience: "isolated-audience" };
  let executions = 0;
  const server = createOpsServer(config, { keys: createLocalJWKSet({ keys: [jwk] }), audit: () => {},
    execute: async () => { executions++; return { exitCode: 0, output: "fake-only" }; } });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const origin = `http://127.0.0.1:${server.address().port}`;
  const token = (sub, aud = config.audience, exp = "5m", human = true) => new SignJWT(human ? { email: "test@example.invalid" } : {})
    .setProtectedHeader({ alg: "RS256", kid: "test" }).setIssuer(config.issuer).setAudience(aud)
    .setSubject(sub).setIssuedAt().setExpirationTime(exp).sign(privateKey);
  const alice = await token("alice"), bob = await token("bob");
  const client = new Client({ name: "isolated", version: "1" });
  const transport = new StreamableHTTPClientTransport(new URL(origin + "/mcp"), {
    requestInit: { headers: { "cf-access-jwt-assertion": alice } } });
  try {
    for (const assertion of ["invalid", await token("alice", "foreign"), await token("alice", config.audience, "-1h")]) {
      assert.equal((await fetch(origin + "/mcp", { method: "POST", headers: { "cf-access-jwt-assertion": assertion } })).status, 403);
    }
    await client.connect(transport);
    assert.equal((await client.listTools()).tools.length, 4);
    const requested = await client.callTool({ name: "ops_request", arguments: { command: "printf isolated", reason: "test" } });
    const request = JSON.parse(requested.content[0].text);
    assert.equal(executions, 0);
    const path = new URL(request.approvalUrl).pathname;
    const headers = { "cf-access-jwt-assertion": alice, cookie: `CF_Authorization=${alice}` };
    assert.equal((await fetch(origin + path, { headers: { ...headers, authorization: "Bearer any" } })).status, 403);
    assert.equal((await fetch(origin + path, { headers: { "cf-access-jwt-assertion": bob, cookie: `CF_Authorization=${bob}` } })).status, 403);
    const page = await fetch(origin + path, { headers });
    assert.equal(page.status, 200);
    const nonce = /name="nonce" value="([a-f0-9]+)"/.exec(await page.text())[1];
    const post = { ...headers, origin: config.origin, "content-type": "application/x-www-form-urlencoded",
      cookie: headers.cookie + `; ops_csrf=${nonce}` };
    const form = new URLSearchParams({ nonce, confirmed: "yes" });
    assert.equal((await fetch(origin + path, { method: "POST", headers: { ...post, origin: "https://attacker.invalid" }, body: form })).status, 403);
    assert.equal((await fetch(origin + path, { method: "POST", headers: post, body: form })).status, 200);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(executions, 1);
    assert.equal((await fetch(origin + path, { method: "POST", headers: post, body: form })).status, 403);
    const result = await client.callTool({ name: "ops_result", arguments: { requestId: request.requestId } });
    assert.equal(JSON.parse(result.content[0].text).result.output, "fake-only");
  } finally {
    await client.close(); server.closeAllConnections(); server.close(); await once(server, "close");
  }
});
