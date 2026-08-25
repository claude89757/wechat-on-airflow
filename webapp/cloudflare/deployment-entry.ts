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

function constantTimeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  if (leftBytes.byteLength !== rightBytes.byteLength) return false;
  let difference = 0;
  for (let index = 0; index < leftBytes.byteLength; index += 1) {
    difference |= leftBytes[index] ^ rightBytes[index];
  }
  return difference === 0;
}

function authorizedInternalRequest(request: Request, env: DeploymentEnv): boolean {
  const authorization = request.headers.get("authorization") || "";
  if (!authorization.startsWith("Bearer ")) return false;
  const token = authorization.slice(7).trim();
  return Boolean(token) && constantTimeEqual(token, env.AIRFLOW_PUSH_TOKEN);
}

async function reconcileSafely(env: DeploymentEnv, limit: number): Promise<void> {
  try {
    await reconcileDeliveryStatuses(withInviteSecrets(env) as never, limit);
  } catch (error) {
    console.warn(JSON.stringify({
      event: "delivery_reconcile_failed",
      reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
    }));
  }
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

    if (request.method === "POST" && url.pathname === "/api/internal/reconcile-deliveries") {
      if (!authorizedInternalRequest(request, env)) {
        return Response.json({ error: "未授权" }, { status: 401 });
      }
      await reconcileSafely(env, 20);
      return Response.json({ success: true }, {
        headers: { "Cache-Control": "no-store" },
      });
    }

    const response = await worker.fetch(request, withInviteSecrets(env) as never, context);
    if (request.method === "POST" && url.pathname === "/api/internal/observations") {
      // Run one provider reconciliation inline. The prior waitUntil-only path was
      // not advancing provider_checked_at in production, while observations are
      // the reliable live heartbeat. A single lookup keeps request latency bounded
      // and guarantees eventual progress without coupling it to maintenance jobs.
      await reconcileSafely(env, 1);
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<void> {
    // Await reconciliation before the legacy maintenance pipeline so unrelated
    // renewal/cleanup failures cannot prevent delivery-state refreshes.
    await reconcileSafely(env, 20);
    await worker.scheduled(controller, withInviteSecrets(env) as never, context);
  },
} satisfies ExportedHandler<DeploymentEnv>;
