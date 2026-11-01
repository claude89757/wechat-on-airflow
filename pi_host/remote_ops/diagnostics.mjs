import { execFile } from "node:child_process";
import { promisify } from "node:util";

const execute = promisify(execFile);
const UNITS = {
  pi: ["zacks-ops-mcp.service", "cloudflared-ops-mcp.service", "pi-appium-mcp.service",
    "cloudflared-appium-mcp.service", "dsh-ydmap-scraper.service", "cloudflared-dsh.service"],
  vps: ["zacks-ops-mcp.service", "cloudflared-ops-mcp.service", "cloudflared.service"],
};
const SERVICES = new Set(["airflow-api-server", "airflow-scheduler", "airflow-dag-processor", "airflow-worker",
  "airflow-triggerer", "zacks-api", "zacks-notification-worker", "zacks-wechat-worker", "postgresql", "redis"]);
const STATES = new Set(["active", "inactive", "failed", "activating", "deactivating", "not-found", "loaded", "masked"]);

export async function diagnose(target, run = execute) {
  if (!Object.hasOwn(UNITS, target)) throw Error("invalid_target");
  const units = [];
  for (const unit of UNITS[target]) {
    try {
      const { stdout } = await run("systemctl", ["show", unit, "--property=LoadState,ActiveState,NRestarts"],
        { timeout: 2000, maxBuffer: 4096, env: { PATH: "/usr/bin:/bin", LANG: "C" } });
      const values = Object.fromEntries(stdout.trim().split("\n").map(line => line.split("=")));
      units.push({ unit, load: STATES.has(values.LoadState) ? values.LoadState : "unknown",
        state: STATES.has(values.ActiveState) ? values.ActiveState : "unknown",
        restarts: /^\d{1,9}$/.test(values.NRestarts) ? Number(values.NRestarts) : null });
    } catch { units.push({ unit, state: "unavailable" }); }
  }
  let containers = null;
  if (target === "vps") {
    try {
      const { stdout } = await run("docker", ["ps", "--all", "--format", "{{json .}}"],
        { timeout: 3000, maxBuffer: 65536, env: { PATH: "/usr/bin:/bin", LANG: "C" } });
      containers = stdout.trim().split("\n").filter(Boolean).map(line => JSON.parse(line)).flatMap(row => {
        const labels = Object.fromEntries(String(row.Labels || "").split(",").map(x => x.split("=")));
        const service = labels["com.docker.compose.service"];
        if (!SERVICES.has(service)) return [];
        return [{ service, state: ["running", "exited", "restarting", "created", "paused", "dead"].includes(row.State) ? row.State : "unknown",
          health: /\(unhealthy\)/.test(row.Status) ? "unhealthy" : /\(healthy\)/.test(row.Status) ? "healthy" : "unknown" }];
      });
    } catch { containers = { state: "unavailable" }; }
  }
  return { target, checkedAt: new Date().toISOString(), units, containers, readOnly: true,
    coverage: "service_state_only_not_delivery_acceptance" };
}
