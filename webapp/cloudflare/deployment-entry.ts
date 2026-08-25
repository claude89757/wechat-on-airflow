import worker from "./index";
import { reconcileDeliveryStatuses } from "./delivery-reconcile";

type DeploymentEnv = Env & {
  DEPLOYMENT_COMMIT?: string;
  VERIFICATION_PEPPER: string;
  AIRFLOW_PUSH_TOKEN: string;
  INVITE_CODE_PEPPER?: string;
  INVITE_ADMIN_TOKEN?: string;
  TENCENT_SECRET_ID: string;
  TENCENT_SECRET_KEY: string;
  TENCENT_REGION: string;
  EMAIL_FROM_ADDRESS: string;
  EMAIL_REPLY_TO: string;
  EMAIL_TEMPLATE_ID: string;
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

function withInviteSecrets(env: DeploymentEnv) {
  return {
    ...env,
    INVITE_CODE_PEPPER: env.INVITE_CODE_PEPPER || env.VERIFICATION_PEPPER,
    INVITE_ADMIN_TOKEN: env.INVITE_ADMIN_TOKEN || env.AIRFLOW_PUSH_TOKEN,
  };
}

function reconcileInBackground(env: DeploymentEnv, context: ExecutionContext, limit = 5) {
  context.waitUntil(
    reconcileDeliveryStatuses(withInviteSecrets(env) as never, limit).catch((error) => {
      console.warn(JSON.stringify({
        event: "delivery_reconcile_background_failed",
        reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
      }));
    }),
  );
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

    const response = await worker.fetch(request, withInviteSecrets(env) as never, context);
    // Observation traffic is already the live heartbeat of this service. Use it
    // as an independent reconciliation trigger so provider-delivery metrics stay
    // fresh even if another scheduled maintenance phase fails before reconciliation.
    if (request.method === "POST" && url.pathname === "/api/internal/observations") {
      reconcileInBackground(env, context, 5);
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<void> {
    // Schedule reconciliation independently before delegating to the legacy
    // maintenance pipeline. One failing maintenance task must not block delivery
    // status refreshes.
    reconcileInBackground(env, context, 20);
    await worker.scheduled(controller, withInviteSecrets(env) as never, context);
  },
} satisfies ExportedHandler<DeploymentEnv>;
