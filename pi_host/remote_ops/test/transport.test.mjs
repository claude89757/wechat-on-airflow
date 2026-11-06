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

test("real HTTP MCP verifies JWT, then runs commands directly for authenticated humans", async () => {
  const { privateKey, publicKey } = await generateKeyPair("RS256");
  const jwk = { ...await exportJWK(publicKey), kid: "test" };
  const config = { origin: "https://pi-mcp.zacks.vision", target: "pi", commit: "a".repeat(40),
    issuer: "https://zacks-vision-ops.cloudflareaccess.com", audience: "isolated-audience" };
  const commands = [];
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const server = createOpsServer(config, { keys: createLocalJWKSet({ keys: [jwk] }), audit: () => {},
    execute: async command => {
      commands.push(command);
      if (command === "slow") await gate;
      return { exitCode: 0, output: `fake-only ${command}` };
    } });
  server.listen(0, "127.0.0.1"); await once(server, "listening");
  const origin = `http://127.0.0.1:${server.address().port}`;
  const token = (sub, aud = config.audience, exp = "5m", human = true) => new SignJWT(human ? { email: "test@example.invalid" } : {})
    .setProtectedHeader({ alg: "RS256", kid: "test" }).setIssuer(config.issuer).setAudience(aud)
    .setSubject(sub).setIssuedAt().setExpirationTime(exp).sign(privateKey);
  const connect = async assertion => {
    const client = new Client({ name: "isolated", version: "1" });
    await client.connect(new StreamableHTTPClientTransport(new URL(origin + "/mcp"), {
      requestInit: { headers: { "cf-access-jwt-assertion": assertion } } }));
    return client;
  };
  const payload = response => JSON.parse(response.content[0].text);
  const alice = await connect(await token("alice")), bob = await connect(await token("bob"));
  const machine = await connect(await token("machine", config.audience, "5m", false));
  try {
    for (const assertion of ["invalid", await token("alice", "foreign"), await token("alice", config.audience, "-1h")]) {
      assert.equal((await fetch(origin + "/mcp", { method: "POST", headers: { "cf-access-jwt-assertion": assertion } })).status, 403);
    }
    assert.equal((await fetch(origin + "/mcp", { method: "POST" })).status, 403);
    assert.deepEqual((await alice.listTools()).tools.map(tool => tool.name).sort(),
      ["ops_diagnose", "ops_exec", "ops_github", "ops_result", "ops_status"]);
    assert.equal(payload(await alice.callTool({ name: "ops_status", arguments: {} })).executionMode, "direct");

    const denied = await machine.callTool({ name: "ops_exec", arguments: { command: "printf machine" } });
    assert.equal(denied.isError, true);
    assert.equal(commands.length, 0);

    const finished = payload(await alice.callTool({ name: "ops_exec", arguments: { command: "printf direct" } }));
    assert.equal(finished.state, "finished");
    assert.equal(finished.result.output, "fake-only printf direct");
    assert.deepEqual(commands, ["printf direct"]);
    const foreign = await bob.callTool({ name: "ops_result", arguments: { requestId: finished.requestId } });
    assert.equal(foreign.isError, true);

    const running = payload(await alice.callTool({ name: "ops_exec", arguments: { command: "slow", waitSeconds: 0 } }));
    assert.equal(running.state, "running");
    release();
    await new Promise(resolve => setImmediate(resolve));
    const done = payload(await alice.callTool({ name: "ops_result", arguments: { requestId: running.requestId } }));
    assert.equal(done.result.output, "fake-only slow");

    const assertion = await token("alice");
    assert.equal((await fetch(`${origin}/approve/${"a".repeat(48)}`, { headers: { "cf-access-jwt-assertion": assertion } })).status, 404);
  } finally {
    await Promise.all([alice.close(), bob.close(), machine.close()]);
    server.closeAllConnections(); server.close(); await once(server, "close");
  }
});
