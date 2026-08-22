import worker from "./index";

type DeploymentEnv = Env & {
  DEPLOYMENT_COMMIT?: string;
};

export function deploymentHealth(deploymentCommit?: string) {
  return {
    ok: true,
    service: "zacks-tennis-alerts",
    deploymentCommit:
      typeof deploymentCommit === "string" && /^[0-9a-f]{40}$/i.test(deploymentCommit)
        ? deploymentCommit
        : "unknown",
  };
}

export default {
  async fetch(
    request: Request,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/api/healthz") {
      return Response.json(deploymentHealth(env.DEPLOYMENT_COMMIT), {
        headers: {
          "Cache-Control": "no-store",
          "Content-Type": "application/json; charset=utf-8",
        },
      });
    }
    return worker.fetch(request, env as never, context);
  },

  async scheduled(
    controller: ScheduledController,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<void> {
    await worker.scheduled(controller, env as never, context);
  },
} satisfies ExportedHandler<DeploymentEnv>;
