import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

test("real upstream registration and HTTP handshake never open a phone session", { timeout: 30000 }, async () => {
  const dir = await mkdtemp(join(tmpdir(), "mcp-transport-"));
  const config = join(dir, "devices.json");
  await writeFile(config, JSON.stringify({ devices: [{ alias: "phone_1", serial: "fake-offline-phone",
    appiumUrl: "http://127.0.0.1:6002", systemPort: 8200 }] }));
  const child = spawn(process.execPath, ["server.mjs"], { cwd: new URL("..", import.meta.url),
    env: { ...process.env, PI_MCP_CONFIG: config, PI_MCP_PORT: "13333" }, stdio: ["ignore", "ignore", "pipe"] });
  let diagnostics = "";
  child.stderr.on("data", chunk => { diagnostics = (diagnostics + chunk.toString()).slice(-10000); });
  const client = new Client({ name: "isolated-test", version: "1.0.0" });
  try {
    let ready = false;
    for (let n = 0; n < 100; n++) {
      assert.equal(child.exitCode, null, `MCP process exited before handshake: ${diagnostics}`);
      try { ready = (await fetch("http://127.0.0.1:13333/health")).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(ready);
    await client.connect(new StreamableHTTPClientTransport(new URL("http://127.0.0.1:13333/mcp")));
    const { tools } = await client.listTools();
    const names = tools.map(t => t.name);
    assert.ok(names.includes("phone_devices"));
    assert.ok(names.includes("appium_screenshot"));
    assert.ok(names.includes("appium_mobile_press_key"));
    for (const blocked of ["select_device", "appium_mobile_file", "appium_mobile_permissions", "appium_mobile_device_control"]) {
      assert.ok(!names.includes(blocked));
    }
    const sessions = await client.callTool({ name: "appium_session_management", arguments: { action: "list" } });
    assert.deepEqual(JSON.parse(sessions.content[0].text), []);
    const devices = await client.callTool({ name: "phone_devices", arguments: {} });
    assert.deepEqual(JSON.parse(devices.content[0].text), [{ device: "phone_1", online: false, platform: "Android" }]);
    const lifecycle = tools.find(t => t.name === "appium_app_lifecycle");
    assert.ok(!lifecycle.inputSchema.properties.action.enum.includes("clear"));
    const screenshot = tools.find(t => t.name === "appium_screenshot");
    assert.ok(!("returnRawBase64" in screenshot.inputSchema.properties));
    await client.close();
    const second = new Client({ name: "reconnect-test", version: "1.0.0" });
    await second.connect(new StreamableHTTPClientTransport(new URL("http://127.0.0.1:13333/mcp")));
    const again = await second.callTool({ name: "appium_session_management", arguments: { action: "list" } });
    assert.equal(again.isError, false);
    await second.close();
  } finally {
    await client.close().catch(() => {});
    child.kill("SIGTERM");
    if (child.exitCode === null) await new Promise(resolve => child.once("exit", resolve));
    await rm(dir, { recursive: true, force: true });
  }
});
