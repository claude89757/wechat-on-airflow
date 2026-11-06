import { createHash, randomBytes } from "node:crypto";
import { spawn } from "node:child_process";

const MAX_OUTPUT = 262144;
export const hash = value => createHash("sha256").update(value).digest("hex");
export function redact(value) {
  return String(value)
    .replace(/-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----/g, "[private key redacted]")
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[jwt redacted]")
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[email redacted]")
    .replace(/((?:password|secret|token|authorization|api[_-]?key)\s*[=:]\s*)[^\s,;]+/gi, "$1[redacted]");
}

export class Operations {
  constructor({ now = Date.now, audit, execute, maximum = 100, maxRunning = 8 }) {
    this.now = now; this.audit = audit; this.execute = execute;
    this.maximum = maximum; this.maxRunning = maxRunning;
    this.items = new Map();
  }
  running() {
    return [...this.items.values()].filter(item => item.state === "running").length;
  }
  sweep() {
    for (const [id, item] of this.items) {
      if (item.state !== "running" && item.expires < this.now()) this.items.delete(id);
    }
  }
  start(principal, command, reason, timeout) {
    this.sweep();
    if (!principal || this.items.size >= this.maximum) throw Error("request_limit");
    if (this.running() >= this.maxRunning) throw Error("host_operation_busy");
    const id = randomBytes(24).toString("hex");
    const item = { id, principal, state: "running", expires: Infinity };
    // Authentication is the only gate, so an unrecorded root command never runs.
    this.audit({ event: "started", id, principal, command: redact(command), reason: redact(reason), timeout });
    this.items.set(id, item);
    const record = event => { try { this.audit({ id, principal, ...event }); } catch {} };
    item.done = Promise.resolve().then(() => this.execute(command, timeout)).then(result => {
      item.result = result; item.state = "finished";
      record({ event: "finished", exitCode: result.exitCode, timedOut: result.timedOut === true });
    }).catch(() => {
      // An interrupted command is never replayed automatically.
      item.state = "unknown";
      record({ event: "unknown" });
    }).finally(() => { item.expires = this.now() + 900000; });
    return item;
  }
  get(id, principal) {
    const item = this.items.get(id);
    if (!item || item.principal !== principal || (item.state !== "running" && item.expires < this.now())) throw Error("request_unavailable");
    return item;
  }
}

export function executeCommand(command, seconds) {
  return new Promise(resolve => {
    let output = "", truncated = false, timedOut = false, done = false;
    const child = spawn("/bin/bash", ["--noprofile", "--norc", "-c", command], { cwd: "/", detached: true,
      env: { PATH: "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", HOME: "/root", LANG: "C.UTF-8" },
      stdio: ["ignore", "pipe", "pipe"] });
    // Keep the end of the output: that is where failures are reported.
    const collect = chunk => {
      output += chunk.toString();
      if (output.length > MAX_OUTPUT) { output = output.slice(-MAX_OUTPUT); truncated = true; }
    };
    child.stdout.on("data", collect); child.stderr.on("data", collect);
    const timer = setTimeout(() => { timedOut = true; try { process.kill(-child.pid, "SIGKILL"); } catch {} }, seconds * 1000);
    const finish = code => {
      if (done) return; done = true; clearTimeout(timer);
      resolve({ exitCode: code, timedOut, truncated, output: redact(output) });
    };
    child.once("error", () => finish(null)); child.once("close", finish);
  });
}
