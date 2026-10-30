import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const client = new Client({ name: "pi-mcp-health", version: "1.0.0" });
try {
  const headers = {};
  if (process.env.CF_ACCESS_CLIENT_ID && process.env.CF_ACCESS_CLIENT_SECRET) {
    headers["CF-Access-Client-Id"] = process.env.CF_ACCESS_CLIENT_ID;
    headers["CF-Access-Client-Secret"] = process.env.CF_ACCESS_CLIENT_SECRET;
  }
  await client.connect(new StreamableHTTPClientTransport(
    new URL(process.env.MCP_URL || "http://127.0.0.1:3333/mcp"), { requestInit: { headers } },
  ));
  const { tools } = await client.listTools();
  if (!tools.some(t => t.name === "phone_devices")) throw new Error("registry_failed");
  const response = await client.callTool({ name: "phone_devices", arguments: {} });
  if (response.isError) throw new Error("device_query_failed");
  const devices = JSON.parse(response.content[0].text);
  const sessions = await client.callTool({ name: "appium_session_management", arguments: { action: "list" } });
  if (sessions.isError) throw new Error("session_status_unknown");
  const owned = JSON.parse(sessions.content[0].text);
  if (!Array.isArray(owned)) throw new Error("session_status_invalid");
  console.log(JSON.stringify({ ok: true, tools: tools.length, configuredDevices: devices.length,
    onlineDevices: devices.filter(d => d.online).length, activePhoneSessions: owned.length,
    phoneSessionsCreated: 0, externalTestSends: 0 }));
} catch {
  console.log(JSON.stringify({ ok: false, failure: "mcp_handshake_or_readonly_probe_failed" }));
  process.exitCode = 1;
} finally { await client.close().catch(() => {}); }
