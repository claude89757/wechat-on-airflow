import worker from "./index";
import {
  reconcileDeliveryLifecycle,
  type DeliveryReconciliationEnv,
} from "./delivery-reconciliation";

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

function withInviteSecrets(env: DeploymentEnv): DeploymentEnv {
  return {
    ...env,
    INVITE_CODE_PEPPER: env.INVITE_CODE_PEPPER || env.VERIFICATION_PEPPER,
    INVITE_ADMIN_TOKEN: env.INVITE_ADMIN_TOKEN || env.AIRFLOW_PUSH_TOKEN,
  };
}

function requestToken(request: Request): string {
  const authorization = request.headers.get("authorization") || "";
  return authorization.startsWith("Bearer ") ? authorization.slice(7).trim() : "";
}

function constantTimeEqual(left: string, right: string): boolean {
  const leftBytes = new TextEncoder().encode(left);
  const rightBytes = new TextEncoder().encode(right);
  if (leftBytes.byteLength !== rightBytes.byteLength) return false;
  let difference = 0;
  for (let index = 0; index < leftBytes.byteLength; index += 1) {
    difference |= leftBytes[index] ^ rightBytes[index];
  }
  return difference === 0;
}

function authorizedInternalRequest(request: Request, env: DeploymentEnv): boolean {
  const token = requestToken(request);
  return Boolean(token) && constantTimeEqual(token, env.AIRFLOW_PUSH_TOKEN);
}

async function reconciliationLimit(request: Request): Promise<number | undefined> {
  try {
    const payload = await request.json<{ limit?: unknown }>();
    const candidate = Number(payload?.limit);
    return Number.isInteger(candidate) && candidate > 0 ? candidate : undefined;
  } catch {
    return undefined;
  }
}

function scheduleDeliveryReconciliation(
  env: DeploymentEnv,
  context: ExecutionContext,
  source: string,
): void {
  context.waitUntil(
    reconcileDeliveryLifecycle(env as DeliveryReconciliationEnv, { source })
      .catch((error) => {
        console.error(JSON.stringify({
          event: "delivery_lifecycle_reconciliation_failed",
          source,
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

    const resolvedEnv = withInviteSecrets(env);
    if (
      request.method === "POST"
      && url.pathname === "/api/internal/delivery-reconcile"
    ) {
      if (!authorizedInternalRequest(request, resolvedEnv)) {
        return Response.json({ error: "未授权" }, { status: 401 });
      }
      try {
        const summary = await reconcileDeliveryLifecycle(
          resolvedEnv as DeliveryReconciliationEnv,
          {
            limit: await reconciliationLimit(request),
            source: "protected-operation",
          },
        );
        return Response.json({ success: true, ...summary }, {
          headers: { "Cache-Control": "no-store" },
        });
      } catch (error) {
        console.error(JSON.stringify({
          event: "protected_delivery_reconciliation_failed",
          reason: error instanceof Error ? error.message.slice(0, 200) : "unknown",
        }));
        return Response.json({ error: "投递状态对账失败" }, { status: 500 });
      }
    }

    const response = await worker.fetch(request, resolvedEnv as never, context);
    if (
      response.ok
      && request.method === "POST"
      && url.pathname === "/api/internal/observations"
    ) {
      // Observation requests already arrive continuously in production. Use
      // them as an independent fallback trigger so provider reconciliation is
      // not starved if an unrelated cron maintenance step fails.
      scheduleDeliveryReconciliation(resolvedEnv, context, "observation");
    }
    return response;
  },

  async scheduled(
    controller: ScheduledController,
    env: DeploymentEnv,
    context: ExecutionContext,
  ): Promise<void> {
    const resolvedEnv = withInviteSecrets(env);
    // Register reconciliation independently before delegating to the legacy
    // scheduled chain. A failure in renewal, expiry mail, draining, or cleanup
    // can no longer prevent delivery-state updates.
    scheduleDeliveryReconciliation(resolvedEnv, context, "scheduled");
    await worker.scheduled(controller, resolvedEnv as never, context);
  },
} satisfies ExportedHandler<DeploymentEnv>;
