export type Env = Cloudflare.Env;

interface SendPayload {
  receiver: string;
  messages: string[];
  device_name: string;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function apiError(status: number, error: string, message: string): Response {
  return jsonResponse({ success: false, error, message }, status);
}

function timingSafeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const leftBytes = encoder.encode(left);
  const rightBytes = encoder.encode(right);
  let mismatch = leftBytes.length ^ rightBytes.length;
  const length = Math.max(leftBytes.length, rightBytes.length);

  for (let index = 0; index < length; index += 1) {
    mismatch |= (leftBytes[index] ?? 0) ^ (rightBytes[index] ?? 0);
  }

  return mismatch === 0;
}

function isAuthorized(request: Request, env: Env): boolean {
  const authorization = request.headers.get("Authorization");
  if (!env.PUBLIC_API_TOKEN || !authorization) {
    return false;
  }
  return timingSafeEqual(authorization, `Bearer ${env.PUBLIC_API_TOKEN}`);
}

function normalizeAgentUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

function isNonEmptyStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.length > 0 && value.every(
    (message) => typeof message === "string" && message.trim() !== "",
  );
}

function validatePayload(value: unknown, allowedDeviceName: string): SendPayload | Response {
  if (value === null || typeof value !== "object") {
    return apiError(400, "invalid_request", "request body must be an object");
  }

  const payload = value as Record<string, unknown>;
  if (typeof payload.receiver !== "string" || payload.receiver.trim() === "") {
    return apiError(400, "invalid_request", "receiver is required");
  }
  if (!isNonEmptyStringArray(payload.messages)) {
    return apiError(400, "invalid_request", "messages must contain non-empty strings");
  }
  if (typeof payload.device_name !== "string" || payload.device_name.trim() === "") {
    return apiError(400, "invalid_request", "device_name is required");
  }
  if (payload.device_name !== allowedDeviceName) {
    return apiError(403, "device_not_allowed", "requested device is not allowed");
  }

  return {
    receiver: payload.receiver,
    messages: payload.messages,
    device_name: payload.device_name,
  };
}

async function readJson(request: Request): Promise<unknown | Response> {
  const contentLength = Number(request.headers.get("Content-Length") ?? "0");
  if (contentLength > 16_384) {
    return apiError(413, "invalid_request", "request body is too large");
  }

  try {
    return await request.json();
  } catch {
    return apiError(400, "invalid_request", "request body must be valid JSON");
  }
}

async function forwardToAgent(payload: SendPayload, env: Env): Promise<Response> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 60_000);

  try {
    const response = await fetch(`${normalizeAgentUrl(env.SENDER_AGENT_URL)}/v1/wechat/send`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.SENDER_AGENT_TOKEN}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const text = await response.text();
    return new Response(text, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : "sender-agent unavailable";
    return apiError(502, "upstream_unavailable", message);
  } finally {
    clearTimeout(timeout);
  }
}

export default {
  async fetch(request: Request, env: Env, _ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/healthz") {
      return jsonResponse({ ok: true, service: "wechat-send-gateway" });
    }
    if (request.method !== "POST" || url.pathname !== "/v1/wechat/send") {
      return apiError(404, "not_found", "endpoint not found");
    }
    if (!isAuthorized(request, env)) {
      return apiError(401, "unauthorized", "missing or invalid bearer token");
    }

    const json = await readJson(request);
    if (json instanceof Response) {
      return json;
    }

    const payload = validatePayload(json, env.ALLOWED_DEVICE_NAME);
    if (payload instanceof Response) {
      return payload;
    }

    return forwardToAgent(payload, env);
  },
} satisfies ExportedHandler<Env>;
