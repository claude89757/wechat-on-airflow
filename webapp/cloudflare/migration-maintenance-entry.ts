/** One-time migration tool only. NEVER used as the production entry after cutover. */
import { hostSecretEnvelope } from "./host-migration-export";
type MigrationEnv = Parameters<typeof hostSecretEnvelope>[1] & { DEPLOYMENT_COMMIT?: string; ASSETS: Fetcher };
export default {
  async fetch(request: Request, env: MigrationEnv): Promise<Response> {
    const path = new URL(request.url).pathname;
    if (path === "/api/edge-healthz") {
      return Response.json({ok: true, runtime: "migration-maintenance", frozen: true,
        deploymentCommit: env.DEPLOYMENT_COMMIT, legacyRuntime: false},
      {headers: {"Cache-Control": "no-store"}});
    }
    if (path === "/api/internal/host-secret-envelope" && request.method === "POST") {
      return hostSecretEnvelope(request, env);
    }
    if (path.startsWith("/api/")) {
      return Response.json({error: "系统迁移维护中，请稍后重试", maintenance: true},
        {status: 503, headers: {"Cache-Control": "no-store", "Retry-After": "30"}});
    }
    return env.ASSETS.fetch(request);
  },
  async scheduled(): Promise<void> {},
} satisfies ExportedHandler<MigrationEnv>;
