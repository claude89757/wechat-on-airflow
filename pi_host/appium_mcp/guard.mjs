import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

export const error = (code) => ({
  isError: true, content: [{ type: "text", text: code }],
});
export const result = (value) => ({
  isError: false, content: [{ type: "text", text: JSON.stringify(value) }],
});

export async function acquireDeviceLock(serial, directory, python = "/usr/bin/python3") {
  const child = spawn(python, [fileURLToPath(new URL("./lock-holder.py", import.meta.url)), serial, directory],
    { stdio: ["pipe", "pipe", "ignore"] });
  return await new Promise((resolve, reject) => {
    let settled = false;
    let output = "";
    const finish = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const timer = setTimeout(() => { child.kill(); finish(null); }, 5000);
    child.on("error", () => { clearTimeout(timer); reject(new Error("lock_unavailable")); });
    child.once("exit", () => finish(null));
    child.stdout.on("data", (chunk) => {
      output += chunk.toString();
      if (output.includes("ready\n")) {
        finish({
          alive: () => child.exitCode === null && !child.killed,
          release: async () => {
            if (child.exitCode !== null) return;
            await new Promise((done) => { child.once("exit", done); child.stdin.end(); });
          },
        });
      } else if (output.includes("busy\n")) finish(null);
    });
  });
}

export async function remoteSessions(device) {
  const response = await fetch(`${device.appiumUrl}/sessions`, {
    signal: AbortSignal.timeout(5000), redirect: "error",
  });
  if (!response.ok) throw new Error("appium_status_unavailable");
  const data = await response.json();
  if (!Array.isArray(data.value)) throw new Error("appium_sessions_invalid");
  return data.value.map(item => item.id || item.sessionId);
}

export class DeviceGuard {
  constructor({ devices, sessions, invokeSession, acquire = acquireDeviceLock,
    inspectRemote = remoteSessions,
    lockDirectory = "/run/wechat-device", idleMs = 30000, maxLeaseMs = 120000, clock = Date.now }) {
    this.devices = devices;
    this.sessions = sessions;
    this.invokeSession = invokeSession;
    this.acquire = acquire;
    this.inspectRemote = inspectRemote;
    this.lockDirectory = lockDirectory;
    this.idleMs = idleMs;
    this.maxLeaseMs = maxLeaseMs;
    this.clock = clock;
    this.owned = new Map();
    this.creating = new Set();
    this.closing = false;
  }

  async manage(args, context) {
    if (this.closing) return error("service_stopping");
    if (args.action === "list") return result([
      ...[...this.owned].map(([sessionId, entry]) => ({ sessionId, device: entry.device.alias, busy: entry.busy })),
      ...[...this.creating].map(device => ({ device, busy: true, creating: true })),
    ]);
    if (args.action === "delete") return await this.close(args.sessionId, context);
    if (args.action !== "create") return error("unsupported_session_action");
    const device = this.devices.find((item) => item.alias === args.device);
    if (!device) return error("unknown_device");
    if (this.creating.has(device.alias) || [...this.owned.values()].some((item) => item.device.alias === device.alias)) {
      return error("device_busy");
    }
    this.creating.add(device.alias);
    let lease;
    let createStarted = false;
    try {
      lease = await this.acquire(device.serial, this.lockDirectory);
      if (!lease) return error("device_busy");
      if ((await this.inspectRemote(device)).length) return error("foreign_session_busy");
      const previous = new Set(this.sessions().map((item) => item.sessionId));
      createStarted = true;
      await this.invokeSession({ action: "create", platform: "android",
        remoteServerUrl: device.appiumUrl,
        capabilities: JSON.stringify({ platformName: "Android", "appium:automationName": "UiAutomator2",
          "appium:udid": device.serial, "appium:deviceName": device.alias,
          "appium:systemPort": device.systemPort, "appium:noReset": true,
          "appium:fullReset": false, "appium:autoLaunch": false,
          "appium:autoGrantPermissions": false, "appium:newCommandTimeout": 45,
          "appium:uiautomator2ServerReadTimeout": 30000 }),
      }, context);
      const created = this.sessions().find((item) => !previous.has(item.sessionId)
        && item.capabilities?.["appium:udid"] === device.serial);
      if (!created) {
        // An empty list cannot rule out a create still running in Appium.
        throw new Error("session_creation_unknown");
      }
      const now = this.clock();
      this.owned.set(created.sessionId, { device, lease, busy: false, created: now, last: now });
      lease = null;
      return result({ sessionId: created.sessionId, device: device.alias,
        idleTimeoutSeconds: this.idleMs / 1000, maximumLeaseSeconds: this.maxLeaseMs / 1000 });
    } catch {
      if (!createStarted) return error("appium_sessions_unavailable");
      // A timed-out create may still own a session. Fence this endpoint rather
      // than release its phone to another controller with an unknown outcome.
      this.closing = true;
      if (lease) this.owned.set(`pending-${device.alias}`, {
        device, lease, busy: true, created: this.clock(), last: this.clock(),
      });
      lease = null;
      return error("session_creation_unknown_recovery_required");
    } finally {
      this.creating.delete(device.alias);
      if (lease) await lease.release();
    }
  }

  async execute(args, callback, context) {
    if (this.closing) return error("service_stopping");
    if (typeof args.sessionId !== "string") return error("explicit_session_id_required");
    const entry = this.owned.get(args.sessionId);
    if (!entry || !entry.lease.alive()) return error("session_not_owned");
    if (entry.busy) return error("device_busy");
    if (this.clock() - entry.created >= this.maxLeaseMs) return error("lease_expired");
    entry.busy = true;
    try { return await callback(args, context); }
    finally { entry.busy = false; entry.last = this.clock(); }
  }

  async close(sessionId, context) {
    if (typeof sessionId !== "string") return error("explicit_session_id_required");
    const entry = this.owned.get(sessionId);
    if (!entry) return error("session_not_owned");
    if (entry.busy) return error("device_busy");
    entry.busy = true;
    try {
      if (!(await this.inspectRemote(entry.device)).includes(sessionId)) {
        // Appium's idle expiry may already have removed the remote session.
        // The stale upstream registry entry is no longer an ownership claim.
        this.owned.delete(sessionId);
        await entry.lease.release();
        return result({ released: true });
      }
      const response = await this.invokeSession({ action: "delete", sessionId }, context);
      if (response?.isError || this.sessions().some((item) => item.sessionId === sessionId)
          || (await this.inspectRemote(entry.device)).includes(sessionId)) {
        return error("session_cleanup_unconfirmed_lock_retained");
      }
      this.owned.delete(sessionId);
      await entry.lease.release();
      return result({ released: true });
    } catch { return error("session_cleanup_failed_lock_retained"); }
    finally { entry.busy = false; }
  }

  async sweep() {
    for (const [id, entry] of this.owned) {
      if (!entry.busy && (this.clock() - entry.last >= this.idleMs || this.clock() - entry.created >= this.maxLeaseMs)) {
        await this.close(id, {});
      }
    }
  }

  async shutdown() {
    this.closing = true;
    const deadline = Date.now() + 45000;
    while ((this.creating.size || [...this.owned.values()].some(e => e.busy)) && Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    for (const id of this.owned.keys()) await this.close(id, {});
  }
}
