import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { spawn } from "node:child_process";

export const hash = value => createHash("sha256").update(value).digest("hex");
export const escapeHtml = value => String(value).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
export function redact(value) {
  return String(value)
    .replace(/-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----/g, "[private key redacted]")
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "[jwt redacted]")
    .replace(/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, "[email redacted]")
    .replace(/((?:password|secret|token|authorization|api[_-]?key)\s*[=:]\s*)[^\s,;]+/gi, "$1[redacted]");
}

export class Requests {
  constructor({ now = Date.now, audit, execute, maximum = 100 }) {
    this.now = now; this.audit = audit; this.execute = execute; this.maximum = maximum;
    this.items = new Map();
  }
  sweep() {
    for (const [id, item] of this.items) {
      if (item.expires < this.now() && item.state !== "running") this.items.delete(id);
    }
  }
  create(principal, command, reason, timeout) {
    this.sweep();
    if (!principal || this.items.size >= this.maximum) throw Error("request_limit");
    const id = randomBytes(24).toString("hex");
    const item = { id, principal, command, reason, timeout, state: "pending",
      digest: hash(command), expires: this.now() + 300000 };
    this.audit({ event: "requested", id, principal, digest: item.digest });
    this.items.set(id, item);
    return item;
  }
  get(id, principal) {
    const item = this.items.get(id);
    if (!item || item.principal !== principal || (item.expires < this.now() && item.state !== "running")) throw Error("request_unavailable");
    return item;
  }
  challenge(id, principal) {
    const item = this.get(id, principal);
    if (item.state !== "pending") throw Error("request_not_pending");
    const nonce = randomBytes(32).toString("hex");
    item.nonceHash = hash(nonce);
    return { item, nonce };
  }
  approve(id, principal, nonce, cookie) {
    const item = this.get(id, principal);
    if ([...this.items.values()].some(x => x.state === "running")) throw Error("host_operation_busy");
    if (item.state !== "pending" || typeof nonce !== "string" || !/^[a-f0-9]{64}$/.test(nonce)
      || nonce !== cookie || !item.nonceHash
      || !timingSafeEqual(Buffer.from(hash(nonce)), Buffer.from(item.nonceHash))) throw Error("confirmation_invalid");
    // Consume before any asynchronous work. A failed/unknown operation is never replayed.
    this.audit({ event: "approved", id, principal, digest: item.digest });
    item.state = "running"; delete item.nonceHash;
    item.expires = this.now() + 900000;
    Promise.resolve().then(() => this.execute(item.command, item.timeout)).then(result => {
      item.result = result; item.state = "finished";
      this.audit({ event: "finished", id, principal, digest: item.digest, exitCode: result.exitCode });
    }).catch(() => {
      item.state = "unknown";
      try { this.audit({ event: "unknown", id, principal, digest: item.digest }); } catch {}
    });
  }
}

export function executeCommand(command, seconds) {
  return new Promise(resolve => {
    let output = "", truncated = false, timedOut = false, done = false;
    const child = spawn("/bin/bash", ["-lc", command], { cwd: "/", detached: true,
      env: { PATH: "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin", HOME: "/root", LANG: "C.UTF-8" },
      stdio: ["ignore", "pipe", "pipe"] });
    const collect = chunk => {
      if (output.length < 65536) output += chunk.toString().slice(0, 65536 - output.length);
      else truncated = true;
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
