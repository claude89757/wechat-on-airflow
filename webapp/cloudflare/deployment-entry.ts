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

function safeError(error: unknown): { type: string; message: string } {
  return {
    type: error instanceof Error ? error.name : "UnknownError",
    message: error instanceof Error ? error.message.slice(0, 240) : "unknown",
  };
}

async function reconcileSafely(env: DeploymentEnv, limit: number): Promise<boolean> {
  try {
    // Pass the original Worker env object. Bindings such as D1 are runtime
    // capabilities and should not be copied through object spread before use.
    await reconcileDeliveryStatuses(env as never, limit);
    return true;
  } catch (error) {
    console.warn(JSON.stringify({ event: "delivery_reconcile_failed", ...safeError(error) }));
    return false;
  }
}

async function eligibleDeliveryCount(env: DeploymentEnv): Promise<number> {
  const result = await env.DB.prepare(
    `SELECT COUNT(DISTINCT message_id) AS count
       FROM notification_outbox
      WHERE status = 'submitted'
        AND message_id IS NOT NULL
        AND message_id NOT LIKE 'worker:%'
        AND (provider_checked_at IS NULL OR provider_checked_at < ?)`,
  ).bind(Date.now() - 5 * 60_000).first<{ count: number }>();
  return Number(result?.count || 0);
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
      try {
        const eligibleBefore = await eligibleDeliveryCount(env);
        await reconcileDeliveryStatuses(env as never, 20);
        const eligibleAfter = await eligibleDeliveryCount(env);
        return Response.json({
          success: true,
          eligibleBefore,
          eligibleAfter,
          progressed: Math.max(0, eligibleBefore - eligibleAfter),
        }, { headers: { "Cache-Control": "no-store" } });
      } catch (error) {
        const safe = safeError(error);
        console.warn(JSON.stringify({ event: "delivery_reconcile_endpoint_failed", ...safe }));
        return Response.json({ success: false, errorType: safe.type, error: safe.message }, {
          status: 500,
          headers: { "Cache-Control": "no-store" },
        });
      }
    }

    const response = await worker.fetch(request, withInviteSecrets(env) as never, context);
    if (request.method === "POST" && url.pathname === "/api/internal/observations") {
      await reconcileSafely(env, 1);
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<void> {
    await reconcileSafely(env, 20);
    await worker.scheduled(controller, withInviteSecrets(env) as never, context);
  },
} satisfies ExportedHandler<DeploymentEnv>;
