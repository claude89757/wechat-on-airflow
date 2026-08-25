import worker from "./index";
import {
  providerCheckError,
  reconcileDeliveryStatuses,
  type DeliveryReconcileSummary,
} from "./delivery-reconcile";

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

function unavailableCount(summary: DeliveryReconcileSummary): number {
  return summary.notifications.unavailable + summary.systemEmails.unavailable;
}

async function reconcileSafely(
  env: DeploymentEnv,
  limit: number,
  source: string,
): Promise<DeliveryReconcileSummary | null> {
  try {
    const summary = await reconcileDeliveryStatuses(withInviteSecrets(env) as never, limit);
    console.log(JSON.stringify({
      event: "delivery_reconcile_completed",
      source,
      summary,
    }));
    return summary;
  } catch (error) {
    const detail = providerCheckError(error);
    console.warn(JSON.stringify({
      event: "delivery_reconcile_failed",
      source,
      errorCode: detail.code,
    }));
    return null;
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
      try {
        const summary = await reconcileDeliveryStatuses(withInviteSecrets(env) as never, 20);
        const unavailable = unavailableCount(summary);
        return Response.json({
          success: unavailable === 0,
          unavailable,
          ...summary,
        }, {
          status: unavailable === 0 ? 200 : 502,
          headers: { "Cache-Control": "no-store" },
        });
      } catch (error) {
        const detail = providerCheckError(error);
        console.error(JSON.stringify({
          event: "protected_delivery_reconcile_failed",
          errorCode: detail.code,
        }));
        return Response.json({
          success: false,
          errorCode: detail.code,
        }, {
          status: 500,
          headers: { "Cache-Control": "no-store" },
        });
      }
    }

    const response = await worker.fetch(request, withInviteSecrets(env) as never, context);
    if (
      response.ok
      && request.method === "POST"
      && url.pathname === "/api/internal/observations"
    ) {
      // One inline lookup guarantees bounded progress on the reliable live
      // observation heartbeat even if another scheduled maintenance phase fails.
      await reconcileSafely(env, 1, "observation");
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<void> {
    // Reconcile before the legacy maintenance chain so renewal, draining, or
    // cleanup errors cannot starve provider delivery-state updates.
    await reconcileSafely(env, 20, "scheduled");
    await worker.scheduled(controller, withInviteSecrets(env) as never, context);
  },
} satisfies ExportedHandler<DeploymentEnv>;
